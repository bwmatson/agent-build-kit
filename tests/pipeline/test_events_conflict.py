"""A conflict event is recorded against the unit and starts no attempt.

A resolve worker counts the attempt, against the pushed head and the base tip, when its run
starts; the poll only clears the count of a conflict that began again.
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


def test_a_conflict_heard_again_records_no_attempt_and_makes_no_move(rig: ConflictRig) -> None:
    rig.conflict()
    rig.conflict()
    rig.conflict()

    assert rig.restacked == []
    stored = rig.stored()
    assert (stored.conflict_tip, stored.conflict_attempts) == ("", 0)
    assert stored.sent_back_for_conflict


def test_a_conflict_that_began_again_clears_the_count_of_the_last(rig: ConflictRig) -> None:
    rig.attempted()
    rig.clock.advance(300)
    began_again = rig.clock.now()

    rig.conflict(since=began_again)

    assert rig.stored().conflict_attempts == 0
    assert rig.stored().sent_back_for_conflict


def test_a_conflict_that_is_the_same_one_keeps_the_count_of_the_last(rig: ConflictRig) -> None:
    rig.attempted(head="an-earlier-head")

    rig.conflict()

    assert rig.stored().conflict_attempts == 1, "only the worker's run changes the count"


def test_a_new_episode_whose_branch_is_busy_has_no_count_from_the_last(rig: ConflictRig) -> None:
    rig.attempted()
    rig.clock.advance(300)
    began_again = rig.clock.now()

    @contextmanager
    def busy(unit):
        raise BranchBusy("being built")
        yield

    rig.claim = busy

    assert rig.conflict(since=began_again) is False
    assert (rig.stored().conflict_tip, rig.stored().conflict_attempts) == ("", 0)


def test_a_base_tip_that_cannot_be_read_does_not_stop_the_conflict_rework_being_recorded(
    rig: ConflictRig,
) -> None:
    def unread(unit):
        raise RuntimeError("no origin/main")

    rig.base_tip = unread

    assert rig.rework(CONFLICT_REASON, ReworkKind.CONFLICT) is True

    stored = rig.stored()
    assert (stored.state, stored.cause) == (PLANNED, Cause.REWORK)
    assert stored.conflict_attempts == 0
