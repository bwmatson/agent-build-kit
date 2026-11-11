"""A resolution run carries the unit through the whole build, with no stop list and no
hand-back (spec: resolution-lane, a resolution run carries the unit through the whole build).

The scene is `test_restack_lane_prepare`'s: a unit in review that the lane runs. What is read is
which agents ran, whether the lane ran them, and what the unit was left as.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline.pr_poller import CONFLICT_REASON
from agent_build_kit.pipeline.restack import Moved
from agent_build_kit.pipeline.unit_store import Cause, ReworkKind
from agent_build_kit.pipeline.units import IN_REVIEW, PLANNED, RUNNING, branch_name
from agent_build_kit.pipeline.wiring import build_restack_onto
from tests.factories import git
from tests.graph.test_restack_lane_prepare import Scene, adapting
from tests.tick_driver import OTHER, UNIT, Setup

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
    """A review comment reaches the unit's thread, as the poller delivers it, which only records
    it; the run the scan finds owed is made in the lane; the number of agent calls before it."""
    before = len(scene.graph.recorder.events)
    moves = len(scene.calls)
    event = ("rework", {"reason": COMMENT, "rework": ReworkKind.COMMENT})
    with cli.build_restack_lane(scene.graph.inst, scene.graph.store) as lane:
        scene.lane = lane
        # The stand-in host numbers the pull request a run opens apart from the scene's: the
        # comment is on the scene's, as in the first round.
        stored = scene.graph.store.get(OTHER)
        scene.graph.store.set_state(OTHER, stored.state, pr=8, branch=stored.branch)
        assert scene.graph.poll(event, pr=8, lane=lane) == [True]
        assert not lane.running and len(scene.calls) == moves, "the poll started nothing"
        # What a resolve worker does for the unit once it is started for it.
        lane.hand_over(scene.graph.store.get(OTHER), claimed=False)
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


def based_on_a_branch(scene: Scene) -> None:
    """The unit's base, its parent's branch, exists, so the lane can read the tip of it."""
    parent = scene.graph.store.get(UNIT)
    git(scene.repo, "branch", parent.branch or branch_name(parent), "main")


def test_comment_reworks_beyond_the_review_rounds_are_each_run_and_never_held(
    scene: Scene,
) -> None:
    based_on_a_branch(scene)
    rounds = scene.graph.inst.config.global_limits.max_review_rounds
    in_the_lane = agents_in_the_lane(scene)

    for _ in range(rounds + 1):
        before = len(scene.graph.recorder.events)
        comment_run(scene)

        assert "claude:rework" in scene.graph.recorder.events[before:], "each comment is reworked"
        stored = scene.graph.store.get(OTHER)
        assert stored.state == IN_REVIEW, stored.note
        assert stored.conflict_attempts == 0, "a comment is no attempt at the base's tip"
    assert in_the_lane["claude:rework"] is True


def test_a_conflict_rework_whose_base_tip_cannot_be_read_is_skipped(scene: Scene) -> None:
    event = ("rework", {"reason": CONFLICT_REASON, "rework": ReworkKind.CONFLICT})
    before = len(scene.graph.recorder.events)

    with cli.build_restack_lane(scene.graph.inst, scene.graph.store) as lane:
        scene.lane = lane
        assert scene.graph.poll(event, pr=8, lane=lane) == [True]
        lane.drain()

    assert "claude:rework" not in scene.graph.recorder.events[before:]
    assert scene.graph.store.get(OTHER).conflict_attempts == 0


def test_a_unit_an_earlier_version_handed_back_is_marked_running_as_a_worker_resumes_it(
    scene: Scene,
) -> None:
    event = ("rework", {"reason": COMMENT, "rework": ReworkKind.COMMENT})
    assert scene.graph.poll(event, pr=8) == [True]
    store = scene.graph.store
    store.set_state(OTHER, PLANNED, note="rework: handed back", cause=Cause.RESTACK_HANDED_BACK)
    recorder = scene.graph.recorder
    seen: list[tuple[str, str]] = []

    def agent(prompt: str, **kwargs: Any) -> str:
        answer = recorder.claude(prompt, **kwargs)
        if recorder.events[-1] == "claude:rework":
            seen.append((store.get(OTHER).state, threading.current_thread().name))
        return answer

    scene.graph.options["run"] = agent

    scene.graph.tick()

    assert seen, "a build worker took the unit up at its step"
    assert all(state == RUNNING for state, _ in seen)
