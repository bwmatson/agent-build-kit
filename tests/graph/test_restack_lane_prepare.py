"""A unit told its base moved while in review is moved by the lane, through `prepare`.

The unit is `running` with `base_changed` and its thread parked at `prepare`, as delivering
the event leaves it. The lane resumes the thread and stops it after `prepare`, so what follows
the move starts in a worker, as for any thread left mid-graph. Only `prepare`'s edges are
faked: the move itself is the pipeline's own, over a real repository whose branch is checked
out in the tree the runner gives `prepare`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.graph.nodes import WAITS
from agent_build_kit.graph.state import Node
from agent_build_kit.pipeline.restack import Moved
from agent_build_kit.pipeline.restack_lane import RestackLane
from agent_build_kit.pipeline.stack_runner import Restacked
from agent_build_kit.pipeline.unit_store import Cause
from agent_build_kit.pipeline.units import PLANNED, RUNNING
from agent_build_kit.pipeline.wiring import build_restack_onto
from tests.factories import git, init_repo, stored_unit
from tests.restack_turn_fakes import commit_file, extra_commit
from tests.tick_driver import OTHER, UNIT, Setup

BRANCH = "spec/add-marker/2"


class Scene:
    """`add-marker/2` was built on `add-marker/1`, which merged; its branch is checked out in
    the repository, still on the old trunk, and its head is approved."""

    def __init__(self, graph: Setup, tmp_path: Path) -> None:
        self.graph = graph
        self.calls: list[bool] = []
        self.lane: RestackLane | None = None
        graph.tick()
        graph.store.upsert([stored_unit(OTHER, depends_on=(UNIT,))])
        graph.tick()
        self.repo = init_repo(graph.inst.checkouts["app"])
        commit_file(self.repo, "a.txt", "a\n")
        git(self.repo, "checkout", "-q", "-b", BRANCH)
        commit_file(self.repo, "own.txt", "own\n")
        self.head = git(self.repo, "rev-parse", "HEAD")
        graph.store.set_state(OTHER, graph.store.get(OTHER).state, pr=8, branch=BRANCH)
        graph.store.record_approval(OTHER, self.head)
        main = extra_commit(self.repo, "main", "b.txt", tmp_path / "scratch")
        git(self.repo, "branch", "-f", "main", main)
        graph.options["worktree"] = lambda unit, base: self.repo
        graph.options["restack_onto"] = self.restack(build_restack_onto(graph.store))

    def in_the_lane(self) -> bool:
        """Whether the lane holds the unit as running: the move is its, not a build worker's."""
        return self.lane is not None and OTHER in self.lane.running

    def restack(self, moving: Any) -> Any:
        def restack(**kwargs: Any) -> Any:
            self.calls.append(self.in_the_lane())
            return moving(**kwargs)

        return restack

    def told_its_base_moved(self) -> None:
        assert self.graph.poll(("merged", {})) == [True]
        stored = self.graph.store.get(OTHER)
        assert (stored.state, stored.cause) == (RUNNING, Cause.BASE_CHANGED)
        assert self.graph.next(OTHER) == (Node.PREPARE,)

    def lane_moves(self) -> None:
        with cli.build_restack_lane(self.graph.inst, self.graph.store) as lane:
            self.lane = lane
            lane.scan(self.graph.store.all())

    def offered(self) -> list[str]:
        graph = self.graph
        return [
            unit.id for unit in cli.resumable_units(graph.inst, graph.store.all(), only=frozenset())
        ]


@pytest.fixture
def scene(graph: Setup, tmp_path: Path) -> Scene:
    return Scene(graph, tmp_path)


def test_the_lane_resumes_the_thread_through_prepare_and_leaves_it_at_the_next_node(
    scene: Scene,
) -> None:
    scene.told_its_base_moved()
    assert scene.offered() == [], "owed a restack, so no worker is started for it"

    scene.lane_moves()

    assert scene.calls == [True], "prepare's move ran in the lane, not in a build worker"
    assert git(scene.repo, "merge-base", "--is-ancestor", "main", BRANCH) == ""
    ahead = scene.graph.next(OTHER)
    assert ahead and Node.PREPARE not in ahead and not set(ahead) & WAITS
    assert scene.offered() == [OTHER], "a worker starts it for what follows"


def test_a_clean_move_of_an_approved_head_keeps_the_approval(scene: Scene) -> None:
    scene.told_its_base_moved()

    scene.lane_moves()

    moved = git(scene.repo, "rev-parse", BRANCH)
    assert moved != scene.head
    assert scene.graph.store.get(OTHER).approved == moved


def test_a_resolved_move_writes_the_predecessor_note_and_leaves_the_head_unapproved(
    scene: Scene,
) -> None:
    def resolving(tree: Path, branch: str, *, new_base: str, old_base: str, **_: Any) -> Moved:
        git(tree, "rebase", "-q", "--onto", new_base, old_base, branch)
        return Moved(sha=git(tree, "rev-parse", "HEAD"), resolved=("a.txt",))

    scene.graph.options["restack_onto"] = scene.restack(
        build_restack_onto(scene.graph.store, move=resolving)
    )
    scene.told_its_base_moved()

    scene.lane_moves()

    stored = scene.graph.store.get(OTHER)
    assert "a.txt" in stored.predecessor_note
    assert stored.approved != git(scene.repo, "rev-parse", BRANCH)
    assert scene.calls == [True]


def test_a_conflict_the_first_two_steps_cannot_settle_leaves_the_unit_planned_for_its_run(
    scene: Scene,
) -> None:
    def conflicts(**kwargs: Any) -> Restacked:
        scene.calls.append(scene.in_the_lane())
        return Restacked(
            onto_unit="main", onto_intent="the trunk", old_base="a", old_head="b", conflict="a.txt"
        )

    scene.graph.options["restack_onto"] = conflicts
    scene.told_its_base_moved()

    scene.lane_moves()

    stored = scene.graph.store.get(OTHER)
    assert (stored.state, stored.cause) == (PLANNED, Cause.RESTACK_CONFLICT)
    assert git(scene.repo, "rev-parse", BRANCH) == scene.head
    assert scene.calls == [True]
