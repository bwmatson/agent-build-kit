"""A comment, a change request or a conflict rework of an in-review unit is handed to the
resolution lane and not left for a build worker (spec: resolution-lane, one lane resolves what an
open pull request waits on).

The lane is a recorder, so a build worker is never asked for: what is read is what the handlers
hand over and what they leave the unit as.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.pipeline.pr_poller import CONFLICT_REASON
from agent_build_kit.pipeline.unit_store import LANE_REWORKS, Cause, FeedbackSource, ReworkKind
from agent_build_kit.pipeline.units import PLANNED
from tests.conflict_event_fakes import UNIT, ConflictRig, FakeLane

COMMENT = "[comment c1] src/app.py:3 — remove this line"


def delivered(*args: object, **kwargs: object) -> bool:
    """A `resume` that reports the event delivered to a parked thread."""
    return True


@pytest.mark.parametrize("kind", [ReworkKind.COMMENT, ReworkKind.CHANGES_REQUESTED])
def test_a_comment_or_a_change_request_is_handed_to_the_lane(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: ReworkKind
) -> None:
    lane = FakeLane()
    rig = ConflictRig(tmp_path, monkeypatch)
    rig.lane = lane

    assert rig.rework(COMMENT, kind) is True

    assert [unit.id for unit, _ in lane.handed] == [UNIT]
    stored = rig.stored()
    assert (stored.state, stored.cause) == (PLANNED, Cause.REWORK)
    assert stored.feedback, "the lane's run has the words to rework"


def test_the_hand_off_takes_exactly_the_kinds_the_scan_owes_a_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    handed = set()
    for kind in ReworkKind:
        lane = FakeLane()
        rig = ConflictRig(tmp_path / kind.value, monkeypatch)
        rig.lane = lane
        rig.rework(COMMENT, kind)
        if lane.handed:
            handed.add(kind)

    assert handed == set(LANE_REWORKS)


def test_a_comment_delivered_to_a_parked_thread_is_handed_over_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lane = FakeLane()
    rig = ConflictRig(tmp_path, monkeypatch)
    rig.lane = lane
    rig.resume = delivered

    assert rig.rework(COMMENT, ReworkKind.COMMENT) is True

    assert [unit.id for unit, _ in lane.handed] == [UNIT], "exactly one hand-over"


def test_a_conflict_rework_with_feedback_of_its_own_is_handed_to_the_lane_too(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lane = FakeLane()
    rig = ConflictRig(tmp_path, monkeypatch)
    rig.lane = lane
    rig.store.record_approval(UNIT, "an-earlier-head")
    rig.store.set_feedback(UNIT, "rename the marker", source=FeedbackSource.REVIEW)

    assert rig.rework(CONFLICT_REASON, ReworkKind.CONFLICT) is True

    assert [unit.id for unit, _ in lane.handed] == [UNIT], "no build worker takes it"


@pytest.mark.parametrize("kind", sorted(LANE_REWORKS, key=lambda kind: kind.value))
def test_a_rework_of_an_in_review_unit_is_recorded_for_the_dispatch_and_starts_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: ReworkKind
) -> None:
    lane = FakeLane()
    rig = ConflictRig(tmp_path, monkeypatch)
    rig.lane = lane

    assert rig.rework(CONFLICT_REASON if kind is ReworkKind.CONFLICT else COMMENT, kind) is True

    assert lane.handed == [], "the poll hands nothing to a lane; a resolve worker is started later"
    assert rig.restacked == []
    assert rig.stored().conflict_attempts == 0
