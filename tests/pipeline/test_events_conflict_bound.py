"""A conflict that survives its attempts holds the unit with a reason.

The bound is `limits.max_review_rounds` attempts at one base tip; an attempt that changed
nothing holds the unit at once.
"""

from pathlib import Path

import pytest

from agent_build_kit.config import active
from agent_build_kit.pipeline.unit_store import HeldBy
from agent_build_kit.pipeline.units import HELD, IN_REVIEW
from tests.conflict_event_fakes import ConflictRig


@pytest.fixture
def rig(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ConflictRig:
    return ConflictRig(tmp_path, monkeypatch)


def test_the_last_attempt_that_leaves_the_conflict_standing_holds_the_unit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = ConflictRig(tmp_path, monkeypatch, pushes=True)
    rounds = active().limits.max_review_rounds
    for _ in range(rounds):
        rig.conflict()
        assert rig.stored().state == IN_REVIEW
    assert rig.stored().conflict_attempts == rounds

    rig.conflict()

    stored = rig.stored()
    assert (stored.state, stored.held_by) == (HELD, HeldBy.REVIEW)
    assert "main" in stored.note
    assert f"moved {rounds} times" in stored.note


def test_a_held_unit_is_not_attempted_again_at_the_same_tip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = ConflictRig(tmp_path, monkeypatch, pushes=True)
    for _ in range(active().limits.max_review_rounds + 1):
        rig.conflict()
    attempts = rig.stored().conflict_attempts
    moves = len(rig.restacked)

    rig.conflict()

    assert rig.stored().conflict_attempts == attempts
    assert len(rig.restacked) == moves
    assert rig.stored().state == HELD


def test_an_attempt_that_left_the_head_unchanged_holds_the_unit_at_once(rig: ConflictRig) -> None:
    rig.conflict()
    assert rig.stored().conflict_attempts == 1

    rig.conflict()

    stored = rig.stored()
    assert (stored.state, stored.held_by) == (HELD, HeldBy.REVIEW)
    assert "changed nothing" in stored.note
    assert len(rig.restacked) == 1
