"""Recordings that no longer answer anything: marked for review when a run shows they are
stale, counted while they wait, and kept or deleted when a person decides."""

from __future__ import annotations

from collections.abc import Collection, Mapping
from pathlib import Path

from agent_build_kit.config import ReplayConfig, RepoConfig
from agent_build_kit.model import Frozen
from agent_build_kit.replay.models import Cassette
from agent_build_kit.replay.state import read_state, write_state
from agent_build_kit.replay.store import (
    cassette_name,
    cassette_path,
    read_cassettes,
    write_cassette,
)

UNASKED = "no run asked for it"


class Stale(Frozen):
    cassette: Cassette
    reason: str
    # No call was made at its index at all, as opposed to one that went live instead.
    unasked: bool


class Waiting(Frozen):
    name: str
    cassette: Cassette
    # What now answers at its test and call index, when something does.
    replacement: Cassette | None = None


def directories(repos: Mapping[str, RepoConfig]) -> dict[str, tuple[Path, ReplayConfig]]:
    """Each repository with a `tests.replay` section, to where its cassettes are and how
    they are configured."""
    return {
        name: (repo.path.expanduser() / repo.tests.replay.directory, repo.tests.replay)
        for name, repo in repos.items()
        if repo.tests.replay is not None
    }


def stale(
    held: Collection[Cassette],
    *,
    asked_keys: Collection[str],
    called: Collection[int],
    missed: Collection[int],
) -> list[Stale]:
    """The cassettes of one test that a passing run shows to be stale: no call was made at
    their index, or the call there went live under another key. Marked ones are not again."""
    found: list[Stale] = []
    for cassette in held:
        if cassette.needs_review or cassette.key in asked_keys:
            continue
        if cassette.call_index not in called:
            found.append(Stale(cassette=cassette, reason=UNASKED, unasked=True))
        elif cassette.call_index in missed:
            reason = f"superseded by a live call at index {cassette.call_index}"
            found.append(Stale(cassette=cassette, reason=reason, unasked=False))
    return found


def mark(directory: Path, found: Stale) -> None:
    marked = found.cassette.model_copy(update={"needs_review": True, "review_reason": found.reason})
    write_cassette(directory, marked)


def unmark(directory: Path, cassette: Cassette) -> None:
    cleared = cassette.model_copy(update={"needs_review": False, "review_reason": ""})
    write_cassette(directory, cleared)


def waiting(directory: Path) -> list[Waiting]:
    """The cassettes marked for review, with what replaced each."""
    every = read_cassettes(directory)
    held: list[Waiting] = []
    for cassette in every:
        if not cassette.needs_review:
            continue
        newer = [
            other
            for other in every
            if other.test_id == cassette.test_id
            and other.call_index == cassette.call_index
            and not other.needs_review
        ]
        replacement = max(newer, key=lambda other: other.recorded_at, default=None)
        name = cassette_name(directory, cassette)
        held.append(Waiting(name=name, cassette=cassette, replacement=replacement))
    return held


def overdue(directory: Path, limit: int) -> list[str]:
    """The waiting cassettes left through more than `limit` runs."""
    runs = read_state(directory).unreviewed_runs
    return [held.name for held in waiting(directory) if runs.get(held.name, 0) > limit]


def count_run(directory: Path) -> None:
    """One more run has passed for each waiting cassette; the others are forgotten."""
    state = read_state(directory)
    counted = {
        held.name: state.unreviewed_runs.get(held.name, 0) + 1 for held in waiting(directory)
    }
    write_state(directory, state.model_copy(update={"unreviewed_runs": counted}))


def keep(directory: Path, name: str) -> bool:
    """Clear the mark on `name`; False when no cassette waits under that name."""
    for held in waiting(directory):
        if held.name == name:
            unmark(directory, held.cassette)
            _forget(directory, name)
            return True
    return False


def delete(directory: Path, name: str) -> bool:
    """Remove the waiting cassette `name`; False when no cassette waits under that name."""
    for held in waiting(directory):
        if held.name == name:
            cassette_path(directory, held.cassette).unlink()
            _forget(directory, name)
            return True
    return False


def _forget(directory: Path, name: str) -> None:
    state = read_state(directory)
    runs = {key: count for key, count in state.unreviewed_runs.items() if key != name}
    write_state(directory, state.model_copy(update={"unreviewed_runs": runs}))
