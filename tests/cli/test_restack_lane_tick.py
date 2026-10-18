"""A tick and its lane: the lane is created once per tick and handed to the poll, the tick
waits for it as it waits for builds, a restack running counts toward the slot occupancy
without waiting for a build slot, and so does the sample row.

A tick is driven as `test_tick_samples` drives it. The poll is a fake that receives the
lane and hands it a restack, which blocks on an event a build or a sample sets, so what
runs beside what is read from the order things happened in, never from the clock.
"""

from __future__ import annotations

import argparse
import json
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline import spans
from agent_build_kit.pipeline.restack_lane import RestackLane
from agent_build_kit.pipeline.stack_runner import RunOutcome, RunStatus
from agent_build_kit.pipeline.unit_store import Cause, StoredUnit, UnitStore
from agent_build_kit.pipeline.units import IN_REVIEW, PLANNED, RUNNING
from agent_build_kit.pipeline.usage_guard import Decision
from agent_build_kit.pipeline.usage_ledger import LEDGER_NAME
from tests.conftest import make_installation
from tests.factories import git, init_repo, new_unit

pytestmark = pytest.mark.usefixtures("scripted_engine")

WAIT = 60
SAMPLE_FIELDS = {
    "kind",
    "at",
    "running",
    "in_review",
    "blocked",
    "queued",
    "free_workers",
    "limit",
    "cap",
}


class Scene:
    """A workspace of two build slots, a build that notes itself, and a poll that hands
    the lane one restack of `second/1`, which is in review, once."""

    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.monkeypatch = monkeypatch
        self.inst: Installation = make_installation(
            tmp_path,
            planning={
                "state_dir": ".",
                "worktree_root": str(tmp_path.with_name(tmp_path.name + "-trees")),
            },
            project_limits={"max_concurrent_stacks": 2, "max_units_in_progress": 50},
        )
        self.store = UnitStore(tmp_path / "units.json")
        self.store.upsert([new_unit("first/1"), new_unit("second/1")])
        self.store.set_state("second/1", IN_REVIEW, pr=9, branch="spec/second/1")
        self.log: list[str] = []
        self.started: list[str] = []
        self.lanes: list[RestackLane] = []
        self.release = threading.Event()
        self.release_on_build = True
        self.hands_over = True
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

    def poll(self, inst: Installation, *, store: UnitStore, lane: RestackLane) -> None:
        self.lanes.append(lane)
        if not self.hands_over:
            return
        self.hands_over = False

        def restack() -> None:
            self.log.append("restack begun")
            assert self.release.wait(WAIT)
            self.log.append("restack done")

        lane.hand_over(self.store.get("second/1"), restack)

    def run(self, unit: StoredUnit, *, base: str, graph: list[StoredUnit]) -> RunOutcome:
        self.started.append(unit.id)
        self.log.append(f"build {unit.id}")
        if (stopped := self.on_build(unit)) is not None:
            return stopped
        self.store.set_state(unit.id, RUNNING, branch=f"spec/{unit.id}")
        self.store.set_state(unit.id, IN_REVIEW, pr=len(self.started))
        self.log.append(f"built {unit.id}")
        if self.release_on_build:
            self.release.set()
        return RunOutcome(status=RunStatus.OPEN, detail=unit.id, pr=len(self.started))

    def tick(self) -> int:
        return cli.cmd_tick(argparse.Namespace(dry_run=False), self.inst)

    def samples(self) -> list[dict[str, Any]]:
        ledger = self.inst.state_dir / LEDGER_NAME
        lines = [json.loads(line) for line in ledger.read_text().splitlines() if line]
        return [line for line in lines if line.get("kind") == "sample"]


@pytest.fixture
def scene(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Scene:
    return Scene(tmp_path, monkeypatch)


def test_a_tick_with_a_restack_in_the_lane_does_not_end_until_it_drains(scene: Scene) -> None:
    assert scene.tick() == 0

    assert scene.log[-1] == "restack done"


def test_a_tick_with_nothing_in_the_lane_ends_as_before(scene: Scene) -> None:
    scene.hands_over = False

    assert scene.tick() == 0

    assert scene.started == ["first/1"]
    (lane,) = set(scene.lanes)
    assert lane.running == lane.waiting == []


def test_a_tick_with_nothing_to_build_still_waits_for_the_lane(scene: Scene) -> None:
    scene.store.set_state("first/1", IN_REVIEW, pr=1, branch="spec/first/1")
    scene.release.set()

    assert scene.tick() == 0

    assert scene.started == []
    assert scene.log == ["restack begun", "restack done"]


def test_a_build_slot_is_free_while_a_restack_runs_and_a_ready_unit_starts_in_it(
    scene: Scene,
) -> None:
    assert scene.tick() == 0

    assert scene.started == ["first/1"]
    assert scene.log == ["restack begun", "build first/1", "built first/1", "restack done"]


def test_the_samples_free_workers_count_the_restack_running_as_occupying_a_slot(
    scene: Scene, monkeypatch: pytest.MonkeyPatch
) -> None:
    during: list[list[str]] = []
    record = spans.record_sample

    def after_the_sample(sample: spans.Sample, log: Callable[[str], None]) -> None:
        record(sample, log)
        during.append(list(scene.lanes[0].running))
        scene.release.set()

    scene.release_on_build = False
    monkeypatch.setattr(spans, "record_sample", after_the_sample)

    assert scene.tick() == 0

    first, *_ = scene.samples()
    assert during[0] == ["second/1"]
    assert set(first) == SAMPLE_FIELDS
    assert (first["free_workers"], first["cap"]) == (1, 2)


def test_a_build_that_stops_for_a_moved_base_is_followed_at_once_by_a_restack_of_it(
    scene: Scene, monkeypatch: pytest.MonkeyPatch
) -> None:
    scene.hands_over = False
    init_repo(scene.inst.checkouts["app"])
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
        scene.log.append("restack")

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

    assert scene.log[:3] == ["build first/1", "restack", "build first/1"]


def test_a_restack_that_leaves_its_unit_owed_is_tried_once_and_the_tick_ends(
    scene: Scene, monkeypatch: pytest.MonkeyPatch
) -> None:
    scene.hands_over = False
    repo = init_repo(scene.inst.checkouts["app"])
    (repo / "a.txt").write_text("a\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "a")
    git(repo, "branch", "spec/second/1")
    (repo / "b.txt").write_text("b\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "b")
    scene.store.set_state(
        "second/1", IN_REVIEW, pr=9, branch="spec/second/1", cause=Cause.BASE_CHANGED
    )
    attempts: list[str] = []

    def deferred(**kwargs: Any) -> None:
        """A restack that cannot move the branch now: the unit is planned for a deferred restack."""
        attempts.append(kwargs["child"].id)
        scene.store.set_state(
            kwargs["child"].id, PLANNED, cause=Cause.RESTACK_DEFERRED, branch="spec/second/1"
        )

    monkeypatch.setattr(cli, "build_restack", lambda **kwargs: deferred)

    assert scene.tick() == 0

    assert attempts == ["second/1"]
