"""A comment, a change request or a conflict rework of an in-review unit is recorded for the
resolve workers and not left for a build worker; the poll starts nothing (spec: resolution-lane,
one lane resolves what an open pull request waits on).

A lane is given to the handlers as a recorder, so what is read is that nothing is handed to it and
what the handlers leave the unit as.
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
def test_a_comment_or_a_change_request_is_recorded_for_a_resolve_worker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: ReworkKind
) -> None:
    rig = ConflictRig(tmp_path, monkeypatch)

    assert rig.rework(COMMENT, kind) is True

    stored = rig.stored()
    assert (stored.state, stored.cause) == (PLANNED, Cause.REWORK)
    assert stored.feedback, "the run has the words to rework"
    assert stored.sent_back_for_rework


def test_the_scan_owes_a_run_for_exactly_the_kinds_the_handler_sends_to_a_resolve_worker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorded = set()
    for kind in ReworkKind:
        rig = ConflictRig(tmp_path / kind.value, monkeypatch)
        rig.rework(COMMENT, kind)
        if rig.stored().sent_back_for_rework:
            recorded.add(kind)

    assert recorded == set(LANE_REWORKS)


def test_a_comment_delivered_to_a_parked_thread_starts_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lane = FakeLane()
    rig = ConflictRig(tmp_path, monkeypatch)
    rig.lane = lane
    rig.resume = delivered

    assert rig.rework(COMMENT, ReworkKind.COMMENT) is True

    assert lane.handed == []


def test_a_conflict_rework_with_feedback_of_its_own_is_recorded_too(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = ConflictRig(tmp_path, monkeypatch)
    rig.store.record_approval(UNIT, "an-earlier-head")
    rig.store.set_feedback(UNIT, "rename the marker", source=FeedbackSource.REVIEW)

    assert rig.rework(CONFLICT_REASON, ReworkKind.CONFLICT) is True

    assert rig.stored().sent_back_for_conflict, "no build worker takes it"


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
