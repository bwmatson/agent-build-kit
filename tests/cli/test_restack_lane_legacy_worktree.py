"""A unit whose worktree is under an earlier folder has its own worktree for the restack: the
branch is checked out there, so the move is left for the unit's run (spec: unit-worktrees)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline.unit_store import Cause
from agent_build_kit.pipeline.units import RUNNING
from tests.cli.test_restack_lane_run_unit import MOVED, Scene
from tests.factories import git

pytestmark = pytest.mark.usefixtures("scripted_engine")


@pytest.fixture
def scene(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Scene:
    return Scene(tmp_path, monkeypatch)


def test_a_worktree_under_an_earlier_folder_is_the_units_own_and_the_move_is_left_for_its_run(
    scene: Scene,
) -> None:
    branch = f"spec/{MOVED}"
    tree = scene.inst.worktree_root / "earlier" / "spec_second_1"
    tree.parent.mkdir(parents=True)
    git(scene.inst.checkouts["app"], "worktree", "add", "-q", str(tree), branch)
    scene.store.set_state(MOVED, RUNNING, branch=branch, cause=Cause.BASE_CHANGED)

    with cli.build_restack_lane(scene.inst, scene.store) as lanes:
        lanes.hand_over(scene.store.get(MOVED))
        lanes.drain()

    left = scene.store.get(MOVED)
    assert left.cause == Cause.RESTACK_CONFLICT
    assert "its worktree has the branch checked out" in left.note
