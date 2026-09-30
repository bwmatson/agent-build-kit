"""The two callables behind a unit's base check: one repo's fetch, and the base
worked out afresh from the forge."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

import pytest

from agent_build_kit.forges.base import PullRequest
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import IN_REVIEW, MERGED, branch_name
from agent_build_kit.pipeline.wiring import build_fetch, build_fresh_base
from tests.factories import git, init_repo, stored_unit, unit
from tests.forges.stand_in import StandInForge, lookup


def _remote_with_checkout(tmp_path: Path) -> tuple[Path, Path, Path]:
    """A bare remote, the checkout a pipeline fetches in, and a second clone
    standing for whoever merges to the trunk."""
    remote = tmp_path / "remote.git"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(remote))
    other = init_repo(tmp_path / "other")
    git(other, "remote", "add", "origin", str(remote))
    git(other, "commit", "-q", "--allow-empty", "-m", "first")
    git(other, "push", "-q", "origin", "main")
    checkout = tmp_path / "checkout"
    git(tmp_path, "clone", "-q", str(remote), str(checkout))
    return remote, checkout, other


def test_a_fetch_brings_the_remote_trunk_up_and_takes_the_repos_turn(tmp_path: Path) -> None:
    _, checkout, other = _remote_with_checkout(tmp_path)
    git(other, "commit", "-q", "--allow-empty", "-m", "merged while the tick ran")
    git(other, "push", "-q", "origin", "main")
    turns: list[str] = []

    @contextmanager
    def turn(repo: str):
        turns.append(f"enter {repo}")
        yield
        turns.append(f"leave {repo}")

    build_fetch({"app": checkout}, turn=turn)(unit(repo="app"))

    assert git(checkout, "rev-parse", "origin/main") == git(other, "rev-parse", "HEAD")
    assert turns == ["enter app", "leave app"]


def test_a_fetch_that_fails_raises_for_the_runner_to_log(tmp_path: Path) -> None:
    _, checkout, _ = _remote_with_checkout(tmp_path)
    git(checkout, "remote", "set-url", "origin", str(tmp_path / "nowhere.git"))

    @contextmanager
    def turn(repo: str):
        yield

    with pytest.raises(RuntimeError):
        build_fetch({"app": checkout}, turn=turn)(unit(repo="app"))


def _stack(tmp_path: Path) -> UnitStore:
    store = UnitStore(tmp_path / "units.json")
    parent = stored_unit("feature/1")
    child = stored_unit("feature/2", depends_on=("feature/1",), groups=(2,))
    store.upsert([parent, child])
    store.set_state(parent.id, IN_REVIEW, pr=5, branch=branch_name(parent))
    return store


def test_a_parent_the_forge_reports_merged_is_recorded_through_the_merge_handler(
    tmp_path: Path,
) -> None:
    store = _stack(tmp_path)
    merged: list[tuple[str, int]] = []
    parent_branch = branch_name(unit("feature/1"))
    forge = StandInForge(prs=[PullRequest(number=5, head=parent_branch, base="main", state=MERGED)])

    def record_merge(repo: str, pr: int) -> None:
        merged.append((repo, pr))
        store.set_state("feature/1", MERGED)  # what the handler does

    fresh = build_fresh_base(store, for_repo=lookup(forge), record_merge=record_merge)

    base = fresh(unit("feature/2", depends_on=("feature/1",)), parent_branch)

    assert merged == [("app", 5)], "the merge is recorded in the unit's repo"
    assert base == "main"


def test_a_parent_still_open_is_left_alone_and_stays_the_base(tmp_path: Path) -> None:
    store = _stack(tmp_path)
    merged: list[tuple[str, int]] = []
    parent_branch = branch_name(unit("feature/1"))
    forge = StandInForge(prs=[PullRequest(number=5, head=parent_branch, base="main", state="open")])
    fresh = build_fresh_base(
        store, for_repo=lookup(forge), record_merge=lambda repo, pr: merged.append((repo, pr))
    )

    base = fresh(unit("feature/2", depends_on=("feature/1",)), parent_branch)

    assert merged == []
    assert base == parent_branch


def test_a_unit_on_the_trunk_asks_the_forge_nothing(tmp_path: Path) -> None:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([stored_unit("feature/1")])
    merged: list[tuple[str, int]] = []
    fresh = build_fresh_base(
        store,
        for_repo=lookup(StandInForge()),
        record_merge=lambda repo, pr: merged.append((repo, pr)),
    )

    assert fresh(unit("feature/1"), "main") == "main"
    assert merged == []
