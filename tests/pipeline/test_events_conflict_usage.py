"""A usage pause does not stop a conflict being recorded.

The pause is the real marker in the rig's state dir. The move, and the choice not to start a
resolver under a pause, are a resolve worker's now: the poll starts no agent and makes no move.
"""

from pathlib import Path

import pytest

from agent_build_kit.pipeline.units import IN_REVIEW
from tests.conflict_event_fakes import ConflictRig


@pytest.mark.parametrize("stacked", [False, True])
def test_a_conflict_under_a_pause_is_recorded_and_makes_no_move(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stacked: bool
) -> None:
    rig = ConflictRig(tmp_path, monkeypatch, stacked=stacked)
    rig.pause()

    assert rig.conflict() is True

    stored = rig.stored()
    assert rig.restacked == []
    assert stored.state == IN_REVIEW
    assert stored.sent_back_for_conflict
    assert stored.conflict_attempts == 0
