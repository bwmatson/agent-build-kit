"""A satisfied unit's pull request is closed by repeating (reason, close) until done."""

from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.forges import RepoId
from agent_build_kit.forges.base import COMMENT_MARKER
from agent_build_kit.pipeline.unit_store import ClosePending, UnitStore
from agent_build_kit.pipeline.units import IN_REVIEW, PLANNED, SATISFIED, Unit, UnitState
from agent_build_kit.pipeline.wiring import build_close_pr
from tests.factories import stored_unit, unit
from tests.forges.stand_in import StandInForge, lookup

REASON = "Task group(s) 1 are implemented elsewhere."
ID = "add-marker/1"


class Remembering(StandInForge):
    """A host that finds a comment it holds by its marker and body, as the real reads do."""

    def comment_exists(
        self, repo: RepoId, pr: int, marker: str, body: str, *, reply_to: str | None = None
    ) -> str | None:
        return "comment-1" if any(marker in c and body == c for c in self.comments) else None


def pending_store(tmp_path: Path, *, pending: ClosePending | None) -> UnitStore:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([stored_unit()])
    store.set_state(ID, SATISFIED, pr=4)
    if pending:
        store.set_close_pending(ID, pending)
    return store


def test_the_reason_is_posted_once_when_the_close_fails_and_is_repeated() -> None:
    host = Remembering(close_error="502 Bad Gateway")
    close = build_close_pr(for_repo=lookup(host))
    with pytest.raises(RuntimeError):
        close(unit(), 4, REASON)
    assert len(host.comments) == 1 and host.closed == []

    host.close_error = ""
    close(unit(), 4, REASON)

    assert host.closed == [4]
    assert len(host.comments) == 1, "the reason was found, not posted again"
    assert COMMENT_MARKER in host.comments[0]


def test_a_pass_retries_a_pending_close_and_removes_the_record_on_success(tmp_path: Path) -> None:
    store = pending_store(tmp_path, pending=ClosePending(pr=4, reason=REASON))
    calls: list[tuple[str, int, str]] = []

    def close(u: Unit, pr: int, reason: str) -> None:
        calls.append((u.id, pr, reason))

    cli.retry_closes(store, close_pr=close)

    assert calls == [(ID, 4, REASON)]
    assert store.get(ID).close_pending is None


def test_a_close_that_fails_again_stays_pending_for_the_next_pass(tmp_path: Path) -> None:
    pending = ClosePending(pr=4, reason=REASON)
    store = pending_store(tmp_path, pending=pending)

    def close(u: Unit, pr: int, reason: str) -> None:
        raise RuntimeError("502 Bad Gateway")

    cli.retry_closes(store, close_pr=close)

    assert store.get(ID).close_pending == pending


@pytest.mark.parametrize("state", [PLANNED, IN_REVIEW])
def test_a_unit_that_left_satisfied_is_not_closed_and_its_record_is_dropped(
    tmp_path: Path, state: UnitState
) -> None:
    """A requeued unit may be reviewing the very pull request the record names."""
    store = pending_store(tmp_path, pending=ClosePending(pr=4, reason=REASON))
    store.set_state(ID, state, pr=4)

    def close(u: Unit, pr: int, reason: str) -> None:
        raise AssertionError("the pull request is under review again")

    cli.retry_closes(store, close_pr=close)

    assert store.get(ID).close_pending is None


def test_a_unit_with_nothing_pending_is_left_alone(tmp_path: Path) -> None:
    store = pending_store(tmp_path, pending=None)

    def close(u: Unit, pr: int, reason: str) -> None:
        raise AssertionError("nothing to close")

    cli.retry_closes(store, close_pr=close)
