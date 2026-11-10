"""A conflict that survives its attempts holds the unit with a reason.

The bound is `global_limits.max_review_rounds` attempts at one base tip; an attempt that changed
nothing holds the unit at once. The attempts are the resolve workers' (`ConflictRig.attempted`);
the poll reads them and holds.
"""

from contextlib import contextmanager
from pathlib import Path

import pytest

from agent_build_kit.config import active
from agent_build_kit.pipeline.unit_store import HeldBy
from agent_build_kit.pipeline.units import HELD, IN_REVIEW
from agent_build_kit.pipeline.workspaces import BranchBusy
from tests.conflict_event_fakes import UNIT, ConflictRig


@pytest.fixture
def rig(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ConflictRig:
    return ConflictRig(tmp_path, monkeypatch)


def test_the_last_attempt_that_leaves_the_conflict_standing_holds_the_unit(
    rig: ConflictRig,
) -> None:
    rounds = active().global_limits.max_review_rounds
    rig.attempted(attempts=rounds, head="an-earlier-head")

    rig.conflict()

    stored = rig.stored()
    assert (stored.state, stored.held_by) == (HELD, HeldBy.REVIEW)
    assert "main" in stored.note
    assert f"moved {rounds} times" in stored.note


def test_a_held_unit_is_not_attempted_again_at_the_same_tip(rig: ConflictRig) -> None:
    rounds = active().global_limits.max_review_rounds
    rig.attempted(attempts=rounds, head="an-earlier-head")
    rig.conflict()

    rig.conflict()

    assert rig.stored().conflict_attempts == rounds
    assert rig.restacked == []
    assert rig.stored().state == HELD


def test_an_attempt_that_left_the_head_unchanged_holds_the_unit_at_once(rig: ConflictRig) -> None:
    rig.attempted()

    rig.conflict()

    stored = rig.stored()
    assert (stored.state, stored.held_by) == (HELD, HeldBy.REVIEW)
    assert "changed nothing" in stored.note
    assert rig.restacked == []


def test_a_hold_on_a_busy_branch_is_offered_again_and_does_not_hold(rig: ConflictRig) -> None:
    rig.attempted()

    @contextmanager
    def busy(unit):
        raise BranchBusy("being built")
        yield

    rig.claim = busy

    assert rig.conflict() is False
    stored = rig.stored()
    assert stored.state == IN_REVIEW
    assert "changed nothing" not in stored.note


def test_a_unit_that_moved_while_the_hold_waited_for_its_claim_is_not_held(
    rig: ConflictRig,
) -> None:
    rig.attempted()

    @contextmanager
    def pushing(unit):
        rig.store.record_push(UNIT, "h2")
        yield

    rig.claim = pushing

    assert rig.conflict() is True
    assert rig.stored().state != HELD
