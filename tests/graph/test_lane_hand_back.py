"""A run in the lane stops before work that is not about the move and hands the unit back
(spec: unit-scheduling, the lane never continues ordinary work).

The unit is told its base moved and the lane makes the whole run; what is read is where the run
stopped, what the unit was left as and where its thread stands.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.graph.state import Node
from agent_build_kit.pipeline.unit_store import Cause, FeedbackSource
from tests.graph.test_restack_lane_prepare import Scene
from tests.lane_hand_back_support import handed_back_at, resolved_move
from tests.runner_fakes import rejecting
from tests.tick_driver import OTHER, Setup


@pytest.fixture
def scene(graph: Setup, tmp_path: Path) -> Scene:
    return Scene(graph, tmp_path)


def test_a_review_asking_for_changes_stops_the_run_before_rework(scene: Scene) -> None:
    resolved_move(scene)
    scene.graph.recorder.verdicts.append(rejecting("rename the marker"))
    scene.told_its_base_moved()

    scene.lane_moves()

    handed_back_at(scene, Node.REWORK)
    assert "review asked for changes" in scene.graph.store.get(OTHER).note
    assert "claude:rework" not in scene.graph.recorder.events


def test_a_failing_check_stops_the_run_before_the_fix(scene: Scene) -> None:
    scene.graph.recorder.unit_test_ok = False
    scene.told_its_base_moved()

    scene.lane_moves()

    handed_back_at(scene, Node.FIX_CHECKS)
    assert "checks" in scene.graph.store.get(OTHER).note
    assert "claude:fix_checks" not in scene.graph.recorder.events


def test_an_end_to_end_unit_stops_the_run_before_its_e2e_tests(
    graph: Setup, tmp_path: Path
) -> None:
    scene = Scene(graph, tmp_path, tier="e2e-test")
    scene.told_its_base_moved()
    built = len(graph.recorder.events)

    scene.lane_moves()

    handed_back_at(scene, Node.E2E)
    assert "e2e-test" not in graph.recorder.events[built:]


def test_a_rework_of_the_conflict_runs_in_the_lane_and_the_next_one_is_handed_back(
    scene: Scene,
) -> None:
    in_the_lane: list[bool] = []
    recorder = scene.graph.recorder

    def agent(prompt: str, **kwargs: object) -> str:
        answer = recorder.claude(prompt, **kwargs)  # type: ignore[arg-type]
        if recorder.events[-1] == "claude:rework":
            in_the_lane.append(scene.in_the_lane())
        return answer

    scene.graph.options["run"] = agent
    scene.graph.store.set_feedback(
        OTHER, "the branch conflicts with main in a.txt", source=FeedbackSource.CONFLICT
    )
    recorder.verdicts.append(rejecting("rename the marker"))
    scene.told_its_base_moved()

    scene.lane_moves()

    assert in_the_lane == [True], "the conflict's rework was run by the lane, once"
    handed_back_at(scene, Node.REWORK)
    assert scene.graph.store.get(OTHER).cause is Cause.RESTACK_HANDED_BACK
