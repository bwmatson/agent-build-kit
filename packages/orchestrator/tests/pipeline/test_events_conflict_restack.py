"""A conflicting unit is sent back for the conflict and the poll makes no move.

The stack move, and the conflict rework after it, are a resolve worker's run; what the poll
leaves is a unit in review sent back for the conflict, whatever its base.
"""

from contextlib import contextmanager
from pathlib import Path

import pytest

from agent_build_kit.pipeline.unit_store import ReworkKind
from agent_build_kit.pipeline.units import IN_REVIEW
from agent_build_kit.pipeline.workspaces import BranchBusy
from tests.conflict_event_fakes import ConflictRig


@pytest.mark.parametrize("stacked", [False, True])
def test_a_conflicting_unit_is_sent_back_for_the_conflict_and_not_moved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stacked: bool
) -> None:
    rig = ConflictRig(tmp_path, monkeypatch, stacked=stacked)

    rig.conflict()

    assert rig.restacked == []
    stored = rig.stored()
    assert stored.state == IN_REVIEW
    assert stored.sent_back_for_conflict
    assert stored.conflict_attempts == 0


def test_a_unit_whose_thread_takes_the_event_goes_to_the_conflict_rework(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = ConflictRig(tmp_path, monkeypatch)
    delivered: list[tuple] = []

    def resume(unit, kind, reason, feedback, **kwargs):
        delivered.append((kind, kwargs.get("rework")))
        return True

    rig.resume = resume

    rig.conflict()

    assert rig.restacked == []
    assert delivered == [("rework", ReworkKind.CONFLICT)]
    assert rig.stored().conflict_attempts == 0, "the thread's run counts it"


def test_a_held_branch_lock_leaves_the_event_for_the_next_poll_and_records_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = ConflictRig(tmp_path, monkeypatch)
    busy = {"on": True}

    @contextmanager
    def claim(unit):
        if busy["on"]:
            raise BranchBusy("being built")
        yield

    rig.claim = claim

    assert rig.conflict() is False
    assert not rig.stored().sent_back_for_conflict

    busy["on"] = False
    assert rig.conflict() is True
    assert rig.stored().sent_back_for_conflict


def test_a_base_tip_that_cannot_be_read_ends_the_event_without_raising(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = ConflictRig(tmp_path, monkeypatch)

    def unread(unit):
        raise RuntimeError("no origin/main")

    rig.base_tip = unread

    assert rig.conflict() is True
    assert rig.restacked == []
    assert rig.stored().conflict_attempts == 0
