"""`abk status` says what a conflicting unit waits for."""

import argparse
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline.pause import PAUSE_MARKER, pause_until
from agent_build_kit.pipeline.pr_poller import PrState, state_path
from agent_build_kit.pipeline.unit_store import Cause, HeldBy, UnitStore
from agent_build_kit.pipeline.units import HELD, IN_REVIEW
from agent_build_kit.pipeline.workspaces import branch_lock
from tests.conftest import make_installation
from tests.factories import stored_unit

SINCE = datetime(2026, 1, 5, 14, 50, tzinfo=UTC)


def status(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    *,
    seen: dict,
    attempts: int = 0,
    held: str = "",
    busy: bool = False,
    pushed: str | None = None,
) -> str:
    """The status line of the one unit, `add-marker/1` with pull request 4, when the last poll
    recorded `seen` for it and the unit has been moved `attempts` times; `busy` holds its
    branch's lock while status is read."""
    inst = make_installation(
        tmp_path, planning={"state_dir": ".", "worktree_root": str(tmp_path.parent / "trees")}
    )
    PrState.save(state_path(tmp_path, "app"), {"4": seen}, "app")
    store = UnitStore(tmp_path / "units.json")
    store.upsert([stored_unit("add-marker/1")])
    store.set_state("add-marker/1", IN_REVIEW, pr=4, branch="spec/add-marker/1")
    if attempts:
        store.record_conflict_attempt(
            "add-marker/1", tip="tip1", head="h1", attempts=attempts, at=SINCE
        )
    if pushed:
        store.record_push("add-marker/1", pushed)
    if held:
        store.set_state(
            "add-marker/1", HELD, note=held, held_by=HeldBy.REVIEW, cause=Cause.NEEDS_HUMAN, pr=4
        )
    monkeypatch.setattr(cli, "current_usage", lambda: None)
    with branch_lock("spec/add-marker/1", root=tmp_path / "locks") if busy else nullcontext():
        assert cli.cmd_status(argparse.Namespace(), inst) == 0
    return next(line for line in capsys.readouterr().out.splitlines() if "add-marker/1" in line)


def conflicting(**overrides) -> dict:
    return {
        "mergeable": False,
        "mergeable_at": (SINCE + timedelta(minutes=10)).isoformat(),
        "conflict_since": SINCE.isoformat(),
        **overrides,
    }


def test_a_conflicting_unit_says_since_when_and_how_often_it_was_moved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    line = status(tmp_path, monkeypatch, capsys, seen=conflicting(), attempts=2)

    assert "conflicts with main since 14:50 UTC; moved 2 times" in line


def test_a_unit_never_moved_says_so_and_that_the_next_poll_moves_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    line = status(tmp_path, monkeypatch, capsys, seen=conflicting())

    assert "moved 0 times" in line
    assert "next poll" in line


def test_a_conflicting_unit_under_a_usage_pause_says_it_waits_for_the_pause_to_end(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    pause_until(
        datetime.now(UTC) + timedelta(hours=1),
        reason="usage window spent",
        marker=tmp_path / PAUSE_MARKER,
    )

    line = status(tmp_path, monkeypatch, capsys, seen=conflicting(), attempts=1)

    assert "usage pause" in line
    assert "next poll" not in line


def test_a_held_conflicting_unit_carries_the_holds_reason_and_says_a_person_is_needed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    reason = (
        "conflicts with main since 14:50 UTC; moved 3 times (base tip tip1): "
        "the last move changed nothing"
    )

    line = status(tmp_path, monkeypatch, capsys, seen=conflicting(), attempts=3, held=reason)

    assert reason in line
    assert line.count("conflicts with main") == 1
    assert "person" in line


def test_a_conflicting_unit_whose_branch_is_being_built_says_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    line = status(tmp_path, monkeypatch, capsys, seen=conflicting(), attempts=1, busy=True)

    assert "its branch is being built" in line
    assert "next poll" not in line


def test_the_count_of_a_conflict_that_began_after_the_last_attempt_reads_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    later = SINCE + timedelta(hours=1)

    line = status(
        tmp_path,
        monkeypatch,
        capsys,
        seen=conflicting(conflict_since=later.isoformat()),
        attempts=3,
    )

    assert "since 15:50 UTC; moved 0 times" in line


def test_an_entry_with_no_conflict_data_prints_the_mark_it_printed_before(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    line = status(tmp_path, monkeypatch, capsys, seen={"mergeable": False})

    assert line.split("] ", 1)[1] == "  awaiting review: add-marker/1 (app) #4 — cannot be merged"
    assert "moved" not in line


def test_a_mergeable_entry_prints_the_line_it_printed_before(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    seen = {"mergeable": True, "mergeable_at": SINCE.isoformat(), "conflict_since": None}

    line = status(tmp_path, monkeypatch, capsys, seen=seen)

    assert line.split("] ", 1)[1] == "  awaiting review: add-marker/1 (app) #4"


@pytest.mark.parametrize(
    "seen",
    [
        {"mergeable": None, "mergeable_at": None, "conflict_since": None},
        {"mergeable": None, "mergeable_at": None, "conflict_since": SINCE.isoformat()},
    ],
    ids=["never determined", "stale conflict start"],
)
def test_an_entry_never_determined_prints_the_line_it_printed_before(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], seen: dict
) -> None:
    line = status(tmp_path, monkeypatch, capsys, seen=seen)

    assert line.split("] ", 1)[1] == "  awaiting review: add-marker/1 (app) #4"


def test_a_conflict_whose_attempts_are_spent_says_the_next_poll_holds_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    line = status(tmp_path, monkeypatch, capsys, seen=conflicting(), attempts=3)

    assert "the next poll holds it for a person unless its base has moved" in line
    assert "moves it" not in line


def test_a_conflict_whose_last_attempt_changed_nothing_says_the_next_poll_holds_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    line = status(tmp_path, monkeypatch, capsys, seen=conflicting(), attempts=1, pushed="h1")

    assert "the next poll holds it for a person unless its base has moved" in line
