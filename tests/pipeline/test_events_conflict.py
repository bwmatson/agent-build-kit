"""A conflict event starts an attempt recorded against the pushed head and the base tip.

The same head at the same tip is never attempted twice; a new tip starts the count at zero.
"""

from contextlib import contextmanager
from pathlib import Path

import pytest

from agent_build_kit.pipeline.pr_poller import CONFLICT_REASON
from agent_build_kit.pipeline.unit_store import Cause, ReworkKind
from agent_build_kit.pipeline.units import PLANNED
from agent_build_kit.pipeline.workspaces import BranchBusy
from tests.conflict_event_fakes import ConflictRig


@pytest.fixture
def rig(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ConflictRig:
    return ConflictRig(tmp_path, monkeypatch)


def test_an_attempt_is_recorded_against_the_head_and_the_base_tip(rig: ConflictRig) -> None:
    rig.conflict()

    stored = rig.stored()
    assert (stored.conflict_tip, stored.conflict_head, stored.conflict_attempts) == (
        "tip1",
        "h1",
        1,
    )
    assert stored.conflict_at == rig.clock.now()


def test_the_same_pushed_head_and_base_tip_is_not_attempted_twice(rig: ConflictRig) -> None:
    rig.conflict()
    rig.conflict()
    rig.conflict()

    assert len(rig.restacked) == 1
    assert rig.stored().conflict_attempts == 1


def test_a_new_pushed_head_at_the_same_tip_is_the_next_attempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = ConflictRig(tmp_path, monkeypatch, pushes=True)
    rig.conflict()

    rig.conflict()

    stored = rig.stored()
    assert (stored.conflict_tip, stored.conflict_head, stored.conflict_attempts) == (
        "tip1",
        "moved-1",
        2,
    )


def test_a_new_base_tip_starts_the_count_at_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = ConflictRig(tmp_path, monkeypatch, pushes=True)
    rig.conflict()
    rig.conflict()
    assert rig.stored().conflict_attempts == 2
    rig.back_in_review("h3")

    rig.tip = "tip2"
    rig.conflict()

    stored = rig.stored()
    assert (stored.conflict_tip, stored.conflict_attempts) == ("tip2", 1)
    assert len(rig.restacked) == 2, "the first attempt at the new tip is the stack move again"


def test_a_definite_true_read_after_an_attempt_starts_the_next_episode_at_zero(
    rig: ConflictRig,
) -> None:
    rig.conflict()
    assert rig.stored().conflict_attempts == 1
    rig.clock.advance(300)
    began_again = rig.clock.now()

    rig.conflict(since=began_again)

    assert rig.stored().conflict_attempts == 1
    assert len(rig.restacked) == 2


def test_the_transition_and_first_sight_dispatches_record_their_attempt_the_same_way(
    rig: ConflictRig,
) -> None:
    rig.rework(CONFLICT_REASON, ReworkKind.CONFLICT)

    stored = rig.stored()
    assert (stored.conflict_tip, stored.conflict_head, stored.conflict_attempts) == (
        "tip1",
        "h1",
        1,
    )

    rig.back_in_review("h1")
    rig.conflict()

    assert rig.restacked == [], "that head at that tip has had its attempt"
    assert rig.stored().conflict_attempts == 1


def test_a_new_episode_whose_move_is_deferred_has_no_count_from_the_last(
    rig: ConflictRig,
) -> None:
    rig.conflict()
    rig.clock.advance(300)
    began_again = rig.clock.now()

    @contextmanager
    def busy(unit):
        raise BranchBusy("being built")
        yield

    rig.claim = busy

    assert rig.conflict(since=began_again) is False
    assert (rig.stored().conflict_tip, rig.stored().conflict_attempts) == ("", 0)


def test_a_base_tip_that_cannot_be_read_still_requeues_the_conflict_rework(
    rig: ConflictRig,
) -> None:
    def unread(unit):
        raise RuntimeError("no origin/main")

    rig.base_tip = unread

    assert rig.rework(CONFLICT_REASON, ReworkKind.CONFLICT) is True

    stored = rig.stored()
    assert (stored.state, stored.cause) == (PLANNED, Cause.REWORK)
    assert stored.conflict_attempts == 0
    assert any("base tip unread" in line for line in rig.logged)
