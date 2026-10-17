"""A unit the lane handed back is taken by a build worker from the step it stopped at, and a
base that moves again is judged afresh (spec: unit-scheduling).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.graph.state import Node
from agent_build_kit.pipeline.restack_lane import moved_base_units
from agent_build_kit.pipeline.unit_store import Cause
from agent_build_kit.pipeline.units import PLANNED
from tests.factories import git
from tests.graph.test_restack_lane_prepare import BRANCH, Scene
from tests.lane_hand_back_support import handed_back_at, move_threads, resolved_move
from tests.runner_fakes import rejecting
from tests.tick_driver import OTHER, Setup


def test_a_worker_runs_a_handed_back_unit_from_its_step_without_moving_the_branch(
    graph: Setup, tmp_path: Path
) -> None:
    scene = Scene(graph, tmp_path)
    resolved_move(scene)
    graph.recorder.verdicts.append(rejecting("rename the marker"))
    scene.told_its_base_moved()
    scene.lane_moves()
    handed_back_at(scene, Node.REWORK)
    head = git(scene.repo, "rev-parse", BRANCH)
    threads = move_threads(scene)
    ran = len(graph.recorder.events)

    graph.tick()

    events = graph.recorder.events[ran:]
    assert events[0] == "claude:rework", "the worker carried on at the step the lane stopped at"
    assert "claude:tests" not in events and "claude:impl" not in events
    assert git(scene.repo, "rev-parse", BRANCH) == head, "the branch was not moved again"
    assert "restack" not in threads, "and no lane worker took the unit"


@pytest.mark.parametrize(
    ("step", "owed"), [(Node.REWORK, False), (Node.E2E, True)], ids=["review-asked", "no-input"]
)
def test_a_handed_back_unit_whose_base_moves_again_is_owed_a_run_only_without_rework_input(
    graph: Setup, tmp_path: Path, step: Node, owed: bool
) -> None:
    if step is Node.REWORK:
        scene = Scene(graph, tmp_path)
        resolved_move(scene)
        graph.recorder.verdicts.append(rejecting("rename the marker"))
    else:
        scene = Scene(graph, tmp_path, tier="e2e-test")
    scene.told_its_base_moved()
    scene.lane_moves()
    handed_back_at(scene, step)

    graph.store.set_state(OTHER, PLANNED, cause=Cause.BASE_CHANGED, branch=BRANCH)

    assert (OTHER in moved_base_units(graph.inst, graph.store.all())) is owed
