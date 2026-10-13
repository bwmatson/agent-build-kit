"""A branch moved twice by another writer while its conflict was resolved, in a run.

The unit is left `planned` to be moved on a later tick, with the branch and both
heads on its record. It is not failed, and the run's one loop back to the restack,
which a moving base is given, is not spent on it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_build_kit.pipeline.restack import BranchMoved
from agent_build_kit.pipeline.unit_store import Cause
from agent_build_kit.pipeline.units import PLANNED
from tests.factories import unit
from tests.graph.test_build_path import build
from tests.graph.test_remaining_paths import fresh

BRANCH = "spec/add-marker/1"
EXPECTED = "a1b2c3d4e5f6a7b8"
FOUND = "9f8e7d6c5b4a3f2e"


def test_a_branch_moved_twice_during_the_resolution_leaves_the_unit_planned(
    tmp_path: Path,
) -> None:
    recorder = fresh(tmp_path)
    asked: list[bool] = []

    def moved_again(**kw: Any) -> None:
        asked.append(kw.get("resolve", True))
        raise BranchMoved(BRANCH, expected=EXPECTED, found=FOUND)

    outcome = build(
        tmp_path,
        recorder,
        branch_commits=lambda cwd, base: 2 + recorder.made,
        restack_onto=moved_again,
    )

    stored = recorder.store.get(unit().id)
    assert outcome.status == "held"
    assert stored.state == PLANNED
    assert stored.cause == Cause.RESTACK_DEFERRED
    assert BRANCH in stored.note
    assert EXPECTED[:12] in stored.note and FOUND[:12] in stored.note
    assert "push" not in recorder.events and "pr" not in recorder.events
    assert asked == [True], "the once-per-run loop back to the restack was not taken"
