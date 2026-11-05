"""A resolution run carries the unit through the whole build, with no stop list and no
hand-back (spec: resolution-lane, a resolution run carries the unit through the whole build).

The scene is `test_restack_lane_prepare`'s: a unit in review that the lane runs. What is read is
which agents ran, whether the lane ran them, and what the unit was left as.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline.restack import Moved
from agent_build_kit.pipeline.unit_store import Cause, ReworkKind
from agent_build_kit.pipeline.units import HELD, IN_REVIEW, PLANNED
from agent_build_kit.pipeline.wiring import build_restack_onto
from tests.factories import git
from tests.graph.test_restack_lane_prepare import Scene, adapting
from tests.runner_fakes import rejecting
from tests.tick_driver import OTHER, Setup

COMMENT = "[comment c1] a.txt:1 — rename the marker"


def resolved_move(scene: Scene) -> None:
    """The move rewrites the diff (a conflict it resolved), and the run's port has nothing to do."""

    def resolving(tree: Path, branch: str, *, new_base: str, old_base: str, **_: Any) -> Moved:
        git(tree, "rebase", "-q", "--onto", new_base, old_base, branch)
        return Moved(sha=git(tree, "rev-parse", "HEAD"), resolved=("a.txt",))

    scene.graph.options["restack_onto"] = scene.restack(
        build_restack_onto(scene.graph.store, move=resolving)
    )
    adapting(scene)


@pytest.fixture
def scene(graph: Setup, tmp_path: Path) -> Scene:
    return Scene(graph, tmp_path)


def comment_run(scene: Scene) -> int:
    """A review comment reaches the unit's thread, as the poller delivers it, and the lane it is
    handed to makes the run; the number of agent calls before the run."""
    before = len(scene.graph.recorder.events)
    event = ("rework", {"reason": COMMENT, "rework": ReworkKind.COMMENT})
    with cli.build_restack_lane(scene.graph.inst, scene.graph.store) as lane:
        scene.lane = lane
        assert scene.graph.poll(event, pr=8, lane=lane) == [True]
        lane.drain()
    return before


def agents_in_the_lane(scene: Scene) -> dict[str, bool]:
    """Wrap the agent so that each step it runs records whether the lane was running the unit."""
    recorder = scene.graph.recorder
    in_the_lane: dict[str, bool] = {}

    def agent(prompt: str, **kwargs: Any) -> str:
        answer = recorder.claude(prompt, **kwargs)
        in_the_lane.setdefault(recorder.events[-1], scene.in_the_lane())
        return answer

    scene.graph.options["run"] = agent
    return in_the_lane


def test_a_comment_run_reworks_checks_reviews_and_pushes_in_the_lane(scene: Scene) -> None:
    in_the_lane = agents_in_the_lane(scene)
    ran = comment_run(scene)

    assert in_the_lane.get("claude:rework") is True, "the rework agent ran in the lane"
    assert "claude:rework" in scene.graph.recorder.events[ran:]
    stored = scene.graph.store.get(OTHER)
    assert stored.state == IN_REVIEW, "the run went on to the push"
    assert scene.offered() == []


def test_a_restack_meeting_a_review_for_changes_reworks_in_the_same_worker(
    scene: Scene,
) -> None:
    resolved_move(scene)
    scene.graph.recorder.verdicts.append(rejecting("rename the marker"))
    in_the_lane = agents_in_the_lane(scene)
    scene.told_its_base_moved()

    scene.lane_moves()

    assert in_the_lane.get("claude:rework") is True, "the lane did the rework itself"
    stored = scene.graph.store.get(OTHER)
    assert stored.state != PLANNED, "not handed back to a build worker"


def test_a_restack_meeting_failing_checks_fixes_them_in_the_same_worker(scene: Scene) -> None:
    scene.graph.recorder.unit_test_ok = False
    in_the_lane = agents_in_the_lane(scene)
    scene.told_its_base_moved()

    scene.lane_moves()

    assert in_the_lane.get("claude:fix_checks") is True, "the lane fixed the checks itself"
    assert scene.graph.store.get(OTHER).state != PLANNED


def test_a_restack_of_an_end_to_end_unit_runs_its_e2e_tests_in_the_lane(
    graph: Setup, tmp_path: Path
) -> None:
    scene = Scene(graph, tmp_path, tier="e2e-test")
    scene.told_its_base_moved()
    built = len(graph.recorder.events)

    scene.lane_moves()

    assert "e2e-test" in graph.recorder.events[built:]
    assert graph.store.get(OTHER).state != PLANNED


def test_a_run_whose_review_rounds_are_spent_is_held_for_a_person_with_a_note(
    scene: Scene,
) -> None:
    resolved_move(scene)
    scene.graph.recorder.verdicts.extend(rejecting("rename the marker") for _ in range(20))
    scene.told_its_base_moved()

    scene.lane_moves()

    stored = scene.graph.store.get(OTHER)
    assert (stored.state, stored.cause) == (HELD, Cause.NEEDS_HUMAN)
    assert stored.note, "the note names the step the run could not finish"
