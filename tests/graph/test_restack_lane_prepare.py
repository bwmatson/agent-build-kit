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
from agent_build_kit.graph.state import Node
from agent_build_kit.pipeline.resolution_lane import Lane
from agent_build_kit.pipeline.unit_store import Cause
from agent_build_kit.pipeline.units import RUNNING
from agent_build_kit.pipeline.wiring import build_restack_onto
from tests.factories import git, init_repo, stored_unit
from tests.restack_turn_fakes import commit_file, extra_commit
from tests.tick_driver import OTHER, UNIT, Setup

BRANCH = "spec/add-marker/2"


class Scene:
    """`add-marker/2` was built on `add-marker/1`, which merged; its branch is checked out in
    the repository, still on the old trunk, and its head is approved."""

    def __init__(self, graph: Setup, tmp_path: Path, **unit_fields: Any) -> None:
        self.graph = graph
        self.calls: list[bool] = []
        self.lane: Lane | None = None
        if unit_fields.get("tier") == "e2e-test":
            # A diff of tests only, which the e2e scope guard allows.
            graph.options["branch_diff"] = lambda cwd, base: (("tests/e2e/test_app.py",), 40)
        graph.tick()
        graph.store.upsert([stored_unit(OTHER, depends_on=(UNIT,), **unit_fields)])
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


def adapting(scene: Scene) -> None:
    """The edges the run's port and accounting reach, which the lane's run goes on into."""
    scene.graph.options["reset_to"] = lambda tree, onto, keep: None
    scene.graph.options["tests_in"] = lambda tree: set()
    scene.graph.options["tests_changed"] = lambda tree, ref: set()
