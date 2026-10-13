"""A usage pause lets a clean conflict move proceed and defers one that needs the resolver.

The pause is the real marker in the rig's state dir; the move is a fake that counts the agent
runs the resolver it is handed would start.
"""

from pathlib import Path

import pytest

from agent_build_kit.pipeline.restack import BranchCheckedOut, Moved
from agent_build_kit.pipeline.unit_store import Cause
from agent_build_kit.pipeline.units import IN_REVIEW, PLANNED
from tests.conflict_event_fakes import ConflictRig, real_restack


class Move:
    """The move `build_restack` makes: clean, or needing a resolver. It calls the resolver it
    is handed, else `real_resolver`, which counts the agent runs a pause must prevent."""

    def __init__(self, *, needs_resolver: bool) -> None:
        self.needs_resolver = needs_resolver
        self.agent_runs = 0

    def real_resolver(self, *args, **kwargs) -> None:
        self.agent_runs += 1

    def __call__(self, *args, resolve=None, **kwargs) -> Moved:
        if not self.needs_resolver:
            return Moved(sha="n")
        (resolve or self.real_resolver)("resolve the conflict")
        return Moved(sha="n", resolved=("a.py",))


def test_a_clean_move_proceeds_under_a_pause(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = ConflictRig(tmp_path, monkeypatch)
    rig.pause()
    pushed: list[str] = []
    rig.restack = real_restack(rig, tmp_path, move=Move(needs_resolver=False), pushed=pushed)

    rig.conflict()

    assert pushed == ["pushed"]
    assert (rig.stored().state, rig.stored().conflict_attempts) == (IN_REVIEW, 1)


def test_a_move_that_needs_the_resolver_never_starts_one_under_a_pause_and_is_tried_after_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = ConflictRig(tmp_path, monkeypatch)
    rig.pause()
    move = Move(needs_resolver=True)
    rig.restack = real_restack(rig, tmp_path, move=move, pushed=[])

    rig.conflict()

    stored = rig.stored()
    assert move.agent_runs == 0, "no agent run while the pause stands"
    assert stored.state == IN_REVIEW, "left where the next poll finds it"
    assert (stored.conflict_tip, stored.conflict_attempts) == ("", 0)

    rig.end_pause()
    rig.conflict()

    stored = rig.stored()
    assert move.agent_runs == 1
    assert (stored.state, stored.cause) == (PLANNED, Cause.RESTACK_DEFERRED)
    assert stored.conflict_attempts == 1


def test_the_rework_under_a_pause_requeues_the_unit_for_the_pass_to_decide(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = ConflictRig(tmp_path, monkeypatch, stacked=True)
    rig.pause()

    rig.conflict()

    stored = rig.stored()
    assert (stored.state, stored.cause) == (PLANNED, Cause.REWORK)
    assert stored.conflict_attempts == 1


def test_a_branch_checked_out_elsewhere_defers_the_move_without_counting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = ConflictRig(tmp_path, monkeypatch)

    def busy(*args, **kwargs):
        raise BranchCheckedOut("spec/add-marker/1", path="/elsewhere")

    rig.restack = real_restack(rig, tmp_path, move=busy, pushed=[])

    rig.conflict()

    stored = rig.stored()
    assert stored.state == IN_REVIEW
    assert (stored.conflict_tip, stored.conflict_attempts) == ("", 0)
