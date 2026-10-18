"""A unit sent back for a conflict has its run started at the move, in the lane, and not in a build
worker (spec: restack-conflicts, a conflict rework starts with the move).

The scene is `test_restack_lane_prepare`'s: `add-marker/2` is in review on a branch behind
`main`, approved, with a real repository under it, so the move that `prepare` makes is the
pipeline's own. Its thread is dropped, so the event meets a unit with none. The poll is the
real `poll_all` over the dispatch, handed a real lane.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.graph.checkpointer import open_checkpointer, unit_graphs_path
from agent_build_kit.graph.state import Node
from agent_build_kit.pipeline.events import build_base_tip
from agent_build_kit.pipeline.pr_poller import CONFLICT_REASON
from agent_build_kit.pipeline.unit_store import HeldBy, ReworkKind
from agent_build_kit.pipeline.units import FAILED, HELD, IN_REVIEW
from tests.factories import git
from tests.graph.test_restack_lane_prepare import BRANCH, Scene
from tests.tick_driver import OTHER, Setup, make_setup

PR = 8
EARLIER = datetime(2026, 1, 1, tzinfo=UTC)


@pytest.fixture
def graph(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Setup:
    return make_setup(tmp_path, monkeypatch)


def without_thread(scene: Scene) -> None:
    """Its parent has merged, and the unit is in review with a pushed head and no thread to
    deliver an event to."""
    scene.told_its_base_moved()

    async def drop() -> None:
        async with open_checkpointer(unit_graphs_path(scene.graph.inst.state_dir)) as saver:
            await saver.adelete_thread(OTHER)

    asyncio.run(drop())
    scene.graph.store.set_state(OTHER, IN_REVIEW, pr=PR, branch=BRANCH)
    scene.graph.store.record_push(OTHER, scene.head)
    assert scene.graph.next(OTHER) == ()
    scene.graph.recorder.logged.clear()


def moved_in_the_lane(scene: Scene) -> bool:
    return bool(scene.calls) and all(scene.calls)


def settled_by_the_move(scene: Scene) -> None:
    """The move settled the conflict: its feedback is gone, and no port or rework agent ran for
    it (the feedback alone would also be gone after a rework that answered it)."""
    logged = scene.graph.recorder.logged
    assert any("restacked onto main cleanly" in line for line in logged)
    assert not any("rework from feedback" in line for line in logged), logged
    assert not any("adapt onto" in line for line in logged), logged
    assert scene.graph.store.get(OTHER).feedback == ""


def test_a_unit_with_no_thread_sent_back_for_a_conflict_starts_at_the_move_in_the_lane(
    graph: Setup, tmp_path: Path
) -> None:
    scene = Scene(graph, tmp_path)
    without_thread(scene)

    with cli.build_restack_lane(graph.inst, graph.store) as lane:
        scene.lane = lane
        answers = graph.poll(
            ("rework", {"reason": CONFLICT_REASON, "rework": ReworkKind.CONFLICT}),
            pr=PR,
            lane=lane,
        )
        lane.drain()

    assert answers == [True]
    assert moved_in_the_lane(scene), "the run began with the move, in a lane worker"
    assert git(scene.repo, "merge-base", "--is-ancestor", "main", BRANCH) == ""
    stored = graph.store.get(OTHER)
    settled_by_the_move(scene)
    assert stored.state != FAILED


def test_a_second_attempt_at_a_tip_for_a_unit_with_no_thread_runs_in_the_lane(
    graph: Setup, tmp_path: Path
) -> None:
    scene = Scene(graph, tmp_path)
    without_thread(scene)
    tip = build_base_tip(graph.store, graph.inst.checkouts)(graph.store.get(OTHER))
    graph.store.record_conflict_attempt(
        OTHER, tip=tip, head="an-earlier-head", attempts=1, at=EARLIER + timedelta(minutes=1)
    )

    with cli.build_restack_lane(graph.inst, graph.store) as lane:
        scene.lane = lane
        answers = graph.poll(
            ("conflict", {"since": EARLIER, "read_at": datetime.now(UTC)}), pr=PR, lane=lane
        )
        lane.drain()

    assert answers == [True]
    assert moved_in_the_lane(scene)
    assert git(scene.repo, "merge-base", "--is-ancestor", "main", BRANCH) == ""
    settled_by_the_move(scene)


def test_an_event_for_a_unit_a_person_holds_is_left_for_the_next_poll_and_taken_then(
    graph: Setup, tmp_path: Path
) -> None:
    scene = Scene(graph, tmp_path)
    without_thread(scene)
    graph.store.set_state(OTHER, HELD, note="a person has it", held_by=HeldBy.REVIEWER)
    event = ("rework", {"reason": CONFLICT_REASON, "rework": ReworkKind.CONFLICT})

    with cli.build_restack_lane(graph.inst, graph.store) as lane:
        scene.lane = lane
        assert graph.poll(event, pr=PR, lane=lane) == [False]
        lane.drain()
        assert scene.calls == [], "nothing moved while it was held"

        graph.store.set_state(OTHER, IN_REVIEW)
        assert graph.poll(event, pr=PR, lane=lane) == [True]
        lane.drain()

    assert moved_in_the_lane(scene)
    assert graph.store.get(OTHER).state != HELD


def test_a_unit_with_a_parked_thread_sent_back_for_a_conflict_is_run_in_the_lane(
    graph: Setup, tmp_path: Path
) -> None:
    scene = Scene(graph, tmp_path)
    scene.told_its_base_moved()
    assert graph.tick() == 0
    assert graph.next(OTHER) == (Node.AWAIT_REVIEW,), "back in review, its thread waiting"
    graph.store.set_state(OTHER, graph.store.get(OTHER).state, pr=PR, branch=BRANCH)
    scene.calls.clear()
    event = ("rework", {"reason": CONFLICT_REASON, "rework": ReworkKind.CONFLICT})

    with cli.build_restack_lane(graph.inst, graph.store) as lane:
        scene.lane = lane
        assert graph.poll(event, pr=PR, lane=lane) == [True]
        lane.drain()

    assert moved_in_the_lane(scene), (
        "the delivered event's run was the lane's, not a build worker's"
    )
