"""The poller's conflict rework, and the conflict handler's later attempts, for a unit owed a
moved-base run are recorded and start nothing: the resolve worker the dispatch starts makes the
run (spec: restack-conflicts, a conflict rework starts with the move; unit-scheduling, a
moved-base run).

A lane is given to the handlers as a recorder, so what is read is that nothing is handed to it
and what the handlers leave the unit as. A run counts its own attempt when it starts, so a
handler that records the conflict adds none.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

from agent_build_kit.pipeline.pr_poller import CONFLICT_REASON
from agent_build_kit.pipeline.unit_store import FeedbackSource, ReworkKind, StoredUnit
from agent_build_kit.pipeline.units import IN_REVIEW
from agent_build_kit.pipeline.workspaces import BranchBusy
from tests.conflict_event_fakes import UNIT, ConflictRig, FakeLane


def test_a_conflict_rework_for_a_unit_owed_a_run_is_recorded_and_returns_at_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lane = FakeLane()
    rig = ConflictRig(tmp_path, monkeypatch)
    rig.lane = lane

    assert rig.rework(CONFLICT_REASON, ReworkKind.CONFLICT) is True

    assert lane.handed == []
    assert rig.restacked == [], "nothing is moved in the poll"
    assert rig.stored().conflict_attempts == 0, "the run counts the attempt, once"


def test_a_unit_with_rework_input_of_its_own_and_one_without_are_both_recorded_and_start_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    own, plain = FakeLane(), FakeLane()
    mine = ConflictRig(tmp_path / "own", monkeypatch)
    mine.lane = own
    mine.store.record_approval(UNIT, "an-earlier-head")
    mine.store.set_feedback(UNIT, "rename the marker", source=FeedbackSource.REVIEW)
    free = ConflictRig(tmp_path / "plain", monkeypatch)
    free.lane = plain

    assert mine.rework(CONFLICT_REASON, ReworkKind.CONFLICT) is True
    assert free.rework(CONFLICT_REASON, ReworkKind.CONFLICT) is True

    assert own.handed == [] and plain.handed == []
    assert free.stored().sent_back_for_conflict


def test_the_second_attempt_at_a_tip_is_recorded_in_review_and_starts_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lane = FakeLane()
    rig = ConflictRig(tmp_path, monkeypatch)
    rig.lane = lane
    rig.conflict()
    rig.back_in_review("h2")

    rig.conflict()

    assert lane.handed == []
    assert rig.stored().state == IN_REVIEW, "not requeued for a build worker"
    assert rig.stored().conflict_attempts == 0, "the run counts it when it starts"


def test_a_busy_branch_returns_false_so_the_poll_offers_it_again_and_it_is_then_recorded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = ConflictRig(tmp_path, monkeypatch)
    busy = {"on": True}

    @contextmanager
    def claim(unit: StoredUnit) -> Iterator[None]:
        if busy["on"]:
            raise BranchBusy("being built")
        yield

    rig.claim = claim

    assert rig.rework(CONFLICT_REASON, ReworkKind.CONFLICT) is False
    assert not rig.stored().sent_back_for_conflict

    busy["on"] = False
    assert rig.rework(CONFLICT_REASON, ReworkKind.CONFLICT) is True
    assert rig.stored().sent_back_for_conflict
    assert rig.stored().conflict_attempts == 0


def delivered(*args: object, **kwargs: object) -> bool:
    """A `resume` that reports the event delivered to a parked thread."""
    return True


@pytest.mark.parametrize("event", ["rework", "conflict"])
def test_a_conflict_delivered_to_a_parked_thread_starts_nothing_and_is_uncounted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, event: str
) -> None:
    lane = FakeLane()
    rig = ConflictRig(tmp_path, monkeypatch)
    rig.lane = lane
    rig.resume = delivered

    if event == "rework":
        rig.rework(CONFLICT_REASON, ReworkKind.CONFLICT)
    else:
        rig.conflict()

    assert lane.handed == []
    assert rig.stored().conflict_attempts == 0, "the thread's run counts the attempt"


@pytest.mark.parametrize("stacked", [False, True])
def test_a_conflict_heard_on_an_in_review_unit_sends_it_back_and_starts_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stacked: bool
) -> None:
    rig = ConflictRig(tmp_path, monkeypatch, stacked=stacked)

    assert rig.conflict() is True

    assert rig.restacked == [], "no move is made in the poll"
    stored = rig.stored()
    assert stored.state == IN_REVIEW
    assert stored.sent_back_for_conflict, "recorded, for the dispatch to start a worker for"
    assert stored.conflict_attempts == 0, "the worker's run counts the attempt, once"


def test_a_conflict_rework_heard_by_the_poller_records_no_attempt_and_starts_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = ConflictRig(tmp_path, monkeypatch)

    assert rig.rework(CONFLICT_REASON, ReworkKind.CONFLICT) is True

    assert rig.restacked == []
    stored = rig.stored()
    assert stored.sent_back_for_conflict
    assert stored.conflict_attempts == 0
