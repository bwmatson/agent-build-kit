"""A conflict rework that changes nothing is not a resolution, whatever was recorded before.

The run ends with the unit back in review at the head it had; the conflict the host still
reports after it holds the unit with the reason, and nothing is dispatched a third time.
"""

from pathlib import Path

import pytest

from agent_build_kit.pipeline.pr_poller import CONFLICT_REASON
from agent_build_kit.pipeline.unit_store import Cause, HeldBy, ReworkKind
from agent_build_kit.pipeline.units import HELD
from tests.conflict_event_fakes import ConflictRig


@pytest.fixture
def rig(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ConflictRig:
    return ConflictRig(tmp_path, monkeypatch)


def test_a_rework_that_changed_nothing_and_a_conflict_still_reported_holds_the_unit(
    rig: ConflictRig,
) -> None:
    rig.rework(CONFLICT_REASON, ReworkKind.CONFLICT)
    rig.back_in_review("h1")

    rig.conflict()

    stored = rig.stored()
    assert (stored.state, stored.held_by) == (HELD, HeldBy.REVIEW)
    assert "changed nothing" in stored.note
    assert stored.cause is not Cause.REWORK, "it is not sent back a second time"


def test_no_third_dispatch_follows_a_rework_that_changed_nothing(rig: ConflictRig) -> None:
    rig.rework(CONFLICT_REASON, ReworkKind.CONFLICT)
    rig.back_in_review("h1")
    rig.conflict()

    rig.conflict()
    rig.conflict()

    assert rig.restacked == []
    stored = rig.stored()
    assert stored.state == HELD
    assert stored.conflict_attempts == 1


def test_a_conflict_recorded_since_before_the_rework_is_the_same_outcome(rig: ConflictRig) -> None:
    """The recorded answer `false` predates the rework, so it proves nothing about the run."""
    rig.rework(CONFLICT_REASON, ReworkKind.CONFLICT)
    rig.back_in_review("h1")

    rig.conflict(since=rig.began)

    stored = rig.stored()
    assert stored.state == HELD
    assert "changed nothing" in stored.note
