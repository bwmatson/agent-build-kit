"""A unit sent back for a conflict is only recorded by the poll: no move is made and nothing is
handed to a lane, so the run that starts at the move is a resolve worker's (spec:
restack-conflicts, a conflict rework starts with the move).

The scene is `test_restack_lane_prepare`'s: `add-marker/2` is in review on a branch behind
`main`, approved, with a real repository under it. Its thread is dropped, so the event meets a unit
with none. The poll is the real `poll_all` over the dispatch.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from agent_build_kit.graph.checkpointer import open_checkpointer, unit_graphs_path
from agent_build_kit.pipeline.events import build_base_tip
from agent_build_kit.pipeline.pr_poller import CONFLICT_REASON
from agent_build_kit.pipeline.unit_store import HeldBy, ReworkKind
from agent_build_kit.pipeline.units import HELD, IN_REVIEW, MERGED
from tests.factories import commit, git, init_repo
from tests.graph.test_restack_lane_prepare import BRANCH, Scene
from tests.tick_driver import OTHER, UNIT, Setup, make_setup

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


def test_a_poll_removes_the_local_branch_of_a_merged_unit_nothing_waits_on(
    graph: Setup,
) -> None:
    repo = init_repo(graph.inst.checkouts["app"])
    commit(repo, "a.txt")
    git(repo, "branch", f"spec/{UNIT}")
    graph.store.set_state(UNIT, MERGED, pr=PR, branch=f"spec/{UNIT}")

    graph.poll()

    assert f"spec/{UNIT}" not in git(repo, "branch", "--format=%(refname:short)").split()


def left_for_a_worker(scene: Scene) -> None:
    """The poll recorded the unit as sent back for the conflict and moved nothing."""
    assert scene.calls == [], "nothing moved in the poll"
    assert scene.graph.store.get(OTHER).sent_back_for_conflict


def test_a_unit_with_no_thread_sent_back_for_a_conflict_is_recorded_and_not_moved(
    graph: Setup, tmp_path: Path
) -> None:
    scene = Scene(graph, tmp_path)
    without_thread(scene)

    answers = graph.poll(
        ("rework", {"reason": CONFLICT_REASON, "rework": ReworkKind.CONFLICT}), pr=PR
    )

    assert answers == [True]
    left_for_a_worker(scene)
    assert graph.store.get(OTHER).conflict_attempts == 0, "the worker's run counts it"


def test_a_second_attempt_at_a_tip_for_a_unit_with_no_thread_is_recorded_and_not_moved(
    graph: Setup, tmp_path: Path
) -> None:
    scene = Scene(graph, tmp_path)
    without_thread(scene)
    tip = build_base_tip(graph.store, graph.inst.checkouts)(graph.store.get(OTHER))
    graph.store.record_conflict_attempt(
        OTHER, tip=tip, head="an-earlier-head", attempts=1, at=EARLIER + timedelta(minutes=1)
    )

    answers = graph.poll(("conflict", {"since": EARLIER, "read_at": datetime.now(UTC)}), pr=PR)

    assert answers == [True]
    left_for_a_worker(scene)
    assert graph.store.get(OTHER).conflict_attempts == 1, "the worker's run counts the next"


def test_an_event_for_a_unit_a_person_holds_is_left_for_the_next_poll_and_taken_then(
    graph: Setup, tmp_path: Path
) -> None:
    scene = Scene(graph, tmp_path)
    without_thread(scene)
    graph.store.set_state(OTHER, HELD, note="a person has it", held_by=HeldBy.REVIEWER)
    event = ("rework", {"reason": CONFLICT_REASON, "rework": ReworkKind.CONFLICT})

    assert graph.poll(event, pr=PR) == [False]
    assert not graph.store.get(OTHER).sent_back_for_conflict, "nothing recorded while held"

    graph.store.set_state(OTHER, IN_REVIEW)
    assert graph.poll(event, pr=PR) == [True]

    left_for_a_worker(scene)
    assert graph.store.get(OTHER).state != HELD
