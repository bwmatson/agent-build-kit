"""A unit with a parked thread whose branch is checked out in its own worktree.

The lane cannot move a branch that is checked out, and has no resolver call to spend on it:
it leaves the move for the unit's own run, which `resumable_units` then offers.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit import runtimes
from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline.unit_store import Cause, UnitStore
from agent_build_kit.pipeline.units import RUNNING
from agent_build_kit.pipeline.workspaces import worktree_path
from tests.factories import git, stored_unit
from tests.restack_lane_fakes import repo_behind

OWED = "feature/3"
BRANCH = "spec/feature/3"


def test_a_parked_unit_with_a_worktree_is_left_for_its_run_with_no_agent_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inst = repo_behind(tmp_path, monkeypatch)
    repo = inst.checkouts["app"]
    tree = worktree_path(repo, BRANCH, inst.worktree_root, name=repo.name)
    tree.parent.mkdir(parents=True, exist_ok=True)
    git(repo, "worktree", "add", "-q", str(tree), BRANCH)
    head = git(repo, "rev-parse", BRANCH)

    def no_agent() -> None:
        pytest.fail("the lane called an agent for a branch it cannot move")

    monkeypatch.setattr(runtimes, "active", no_agent)
    store = UnitStore(tmp_path / "units.json")
    store.upsert([stored_unit(OWED, change="feature")])
    store.set_state(OWED, RUNNING, branch=BRANCH, cause=Cause.BASE_CHANGED)
    assert cli.resumable_units(inst, store.all(), only=frozenset()) == []

    with cli.build_restack_lane(inst, store) as lane:
        lane.scan(store.all())

    assert store.get(OWED).cause is Cause.RESTACK_CONFLICT
    assert git(repo, "rev-parse", BRANCH) == head
    assert [unit.id for unit in cli.resumable_units(inst, store.all(), only=frozenset())] == [OWED]
