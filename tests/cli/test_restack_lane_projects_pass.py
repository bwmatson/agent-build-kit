"""The pass and the lanes of its projects: a restack running in the lane of one project
keeps the pass going and does not hold back a restack of another, and the cap of a lane is
`project_limits.max_concurrent_restacks`.

A tick is driven as `test_restack_lane_tick` drives it: the poll is a fake that receives the
lanes and hands them restacks that wait on events, so what runs beside what is read from the
order things happened in, never from the clock.
"""

from __future__ import annotations

import argparse
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.restack_lane import Lane
from agent_build_kit.pipeline.stack_runner import RunOutcome, RunStatus
from agent_build_kit.pipeline.unit_store import Cause, StoredUnit, UnitStore
from agent_build_kit.pipeline.units import IN_REVIEW, PLANNED, RUNNING
from agent_build_kit.pipeline.usage_guard import Decision
from tests.conftest import make_installation
from tests.factories import init_repo, new_unit

pytestmark = pytest.mark.usefixtures("scripted_engine")

WAIT = 60
OTHER_BEGINS = 5  # how long a restack waits for the one beside it before the test fails


class Scene:
    """Two build slots and a restack lane of one worker for each project: `first/1` is a ready
    unit of project `web`, `second/1` and `third/1` are in review in projects `api` and `.`."""

    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.inst: Installation = make_installation(
            tmp_path,
            planning={
                "state_dir": ".",
                "worktree_root": str(tmp_path.with_name(tmp_path.name + "-trees")),
            },
            project_limits={"max_concurrent_stacks": 2, "max_concurrent_restacks": 1},
        )
        self.store = UnitStore(tmp_path / "units.json")
        self.store.upsert(
            [
                new_unit("first/1", project="web"),
                new_unit("second/1", project="api"),
                new_unit("third/1"),
            ]
        )
        for name, pr in (("second/1", 9), ("third/1", 10)):
            self.store.set_state(name, IN_REVIEW, pr=pr, branch=f"spec/{name}")
        self.log: list[str] = []
        self.started: list[str] = []
        self.release = threading.Event()
        self.patience = WAIT
        self.handed = ["second/1", "third/1"]
        self.begun: dict[str, threading.Event] = {}
        self.on_build: Callable[[StoredUnit], RunOutcome | None] = lambda unit: None
        for name, step in {
            "fetch_all": lambda inst: None,
            "plan_all": lambda inst, **kwargs: None,
            "has_identity": lambda inst, repo: True,
            "verify_ready": lambda inst, units, **kwargs: lambda change: True,
            "archive_ready_changes": lambda *a, **k: [],
            "current_usage": lambda: None,
            "may_start_unit": lambda r: Decision(may_start=True, reason="plenty"),
            "poll_all": self.poll,
            "build_runner": lambda unit, **kwargs: self,
        }.items():
            monkeypatch.setattr(cli, name, step)

    def poll(self, inst: Installation, *, store: UnitStore, lane: Lane) -> None:
        handed, self.handed = self.handed, []
        self.hand_over(lane, handed)

    def hand_over(
        self, lane: Lane, unit_ids: list[str], *, running: list[str] | None = None
    ) -> None:
        """Hand the units over; those in `running` (all, by default) wait for each other to
        begin, so a unit expected to wait does not need its siblings to begin."""
        beside = unit_ids if running is None else running
        for unit_id in unit_ids:
            self.begun[unit_id] = threading.Event()
        for unit_id in unit_ids:
            others = beside if unit_id in beside else []
            lane.hand_over(self.store.get(unit_id), self.restack(unit_id, others))

    def restack(self, unit_id: str, beside: list[str]) -> Callable[[], None]:
        def work() -> None:
            self.log.append(f"{unit_id} begun")
            self.begun[unit_id].set()
            for other in beside:
                # Each waits for the others: a lane shared by all would never let it begin.
                assert self.begun[other].wait(OTHER_BEGINS), other + " never began"
            assert self.release.wait(self.patience)
            self.log.append(f"{unit_id} done")

        return work

    def run(self, unit: StoredUnit, *, base: str, graph: list[StoredUnit]) -> RunOutcome:
        self.started.append(unit.id)
        self.log.append(f"build {unit.id}")
        if (stopped := self.on_build(unit)) is not None:
            return stopped
        self.store.set_state(unit.id, RUNNING, branch=f"spec/{unit.id}")
        self.store.set_state(unit.id, IN_REVIEW, pr=len(self.started))
        self.release.set()
        return RunOutcome(status=RunStatus.OPEN, detail=unit.id, pr=len(self.started))

    def tick(self) -> int:
        return cli.cmd_tick(argparse.Namespace(dry_run=False), self.inst)


@pytest.fixture
def scene(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Scene:
    return Scene(tmp_path, monkeypatch)


def test_a_pass_with_restacks_running_in_two_projects_lanes_does_not_end_while_either_has_work(
    scene: Scene,
) -> None:
    assert scene.tick() == 0

    assert sorted(scene.log[-2:]) == ["second/1 done", "third/1 done"]


def test_a_restack_that_ends_after_a_round_left_its_unit_out_is_followed_by_one_more_round(
    scene: Scene, monkeypatch: pytest.MonkeyPatch
) -> None:
    init_repo(scene.inst.checkouts["app"])
    scene.handed = ["second/1"]
    restacked: list[str] = []
    stopped: list[str] = []

    def stops_once(unit: StoredUnit) -> RunOutcome | None:
        if stopped:
            return None
        stopped.append(unit.id)
        scene.store.set_state(unit.id, PLANNED, cause=Cause.BASE_CHANGED, branch="spec/first/1")
        return RunOutcome(status=RunStatus.SKIPPED, detail="the base moved")

    def restack(**kwargs: Any) -> None:
        restacked.append(kwargs["child"].id)
        scene.log.append("restack first/1")
        scene.release.set()

    def owed(inst: Installation, units: list[StoredUnit]) -> set[str]:
        return {
            unit.id
            for unit in units
            if unit.cause is Cause.BASE_CHANGED and unit.id not in restacked
        }

    scene.on_build = stops_once
    monkeypatch.setattr(cli, "build_restack", lambda **kwargs: restack)
    monkeypatch.setattr(cli, "owed_units", owed)

    assert scene.tick() == 0

    assert scene.log.count("build first/1") == 2
    # `second/1` holds its project's only worker until `first/1`, of another project, is moved.
    assert scene.log.index("restack first/1") < scene.log.index("second/1 done")


def test_each_project_of_a_repo_runs_max_concurrent_restacks_from_project_limits(
    scene: Scene,
) -> None:
    scene.store.upsert([new_unit("first/2", project="web")])
    with cli.build_restack_lane(scene.inst, scene.store) as lane:
        scene.hand_over(lane, ["first/1", "first/2", "second/1"], running=["first/1", "second/1"])

        assert scene.begun["first/1"].wait(WAIT)
        assert scene.begun["second/1"].wait(WAIT)
        assert sorted(lane.running) == ["first/1", "second/1"]
        assert lane.waiting == ["first/2"]
        assert not scene.begun["first/2"].is_set()
        scene.release.set()
