"""The poller's conflict rework, and the conflict handler's later attempts, for a unit owed a
moved-base run are handed to the lane and not left for a build worker (spec: restack-conflicts,
a conflict rework starts with the move; unit-scheduling, a moved-base run).

The lane is a recorder, so a build worker is never asked for: what is read is what the handlers
hand over and answer. A run the lane makes counts its own attempt when it starts, so a handler
that hands a unit over adds none.
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


def handed_ids(lane: FakeLane) -> list[str]:
    return [unit.id for unit, _ in lane.handed]


def test_a_conflict_rework_for_a_unit_owed_a_run_is_handed_over_and_returns_at_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lane = FakeLane()
    rig = ConflictRig(tmp_path, monkeypatch)
    rig.lane = lane

    assert rig.rework(CONFLICT_REASON, ReworkKind.CONFLICT) is True

    assert handed_ids(lane) == [UNIT]
    assert rig.restacked == [], "nothing is moved in the poll"
    assert rig.stored().conflict_attempts == 0, "the lane's run counts the attempt, once"


def test_a_unit_with_rework_input_of_its_own_is_sent_back_as_it_is_and_one_without_is_handed_over(
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

    assert own.handed == [], "its rework is a build, for a build worker"
    assert handed_ids(plain) == [UNIT]


def test_the_second_attempt_at_a_tip_is_handed_to_the_lane_instead_of_requeuing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lane = FakeLane()
    rig = ConflictRig(tmp_path, monkeypatch)
    rig.lane = lane
    rig.conflict()
    ((_, move),) = lane.handed
    assert move is not None
    move()
    assert rig.stored().conflict_attempts == 1
    rig.back_in_review("h2")

    rig.conflict()

    assert handed_ids(lane) == [UNIT, UNIT], "the second attempt goes to the lane as well"
    assert rig.stored().state == IN_REVIEW, "not requeued for a build worker"
    assert rig.stored().conflict_attempts == 1, "the lane's run counts it when it starts"


def test_the_attempt_for_a_stacked_unit_is_handed_to_the_lane_instead_of_requeuing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lane = FakeLane()
    rig = ConflictRig(tmp_path, monkeypatch, stacked=True)
    rig.lane = lane

    rig.conflict()

    assert handed_ids(lane) == [UNIT]
    assert rig.restacked == []
    assert rig.stored().state == IN_REVIEW


def test_a_busy_branch_returns_false_so_the_poll_offers_it_again_and_it_is_then_handed_over(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lane = FakeLane()
    rig = ConflictRig(tmp_path, monkeypatch)
    rig.lane = lane
    busy = {"on": True}

    @contextmanager
    def claim(unit: StoredUnit) -> Iterator[None]:
        if busy["on"]:
            raise BranchBusy("being built")
        yield

    rig.claim = claim

    assert rig.rework(CONFLICT_REASON, ReworkKind.CONFLICT) is False
    assert lane.handed == []
    assert rig.stored().conflict_attempts == 0

    busy["on"] = False
    assert rig.rework(CONFLICT_REASON, ReworkKind.CONFLICT) is True
    assert handed_ids(lane) == [UNIT], "handed over once, by the offer that took it"
    assert rig.stored().conflict_attempts == 0
