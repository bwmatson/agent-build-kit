"""The occupancy of a project is a set of unit ids: the builds in flight, the moved-base runs
running in the lane and the stored-`running` units, each counted once, and work waiting behind the
lane's cap not at all. It is counted for each project, and the lane's admission, `owed_units` and
the scan never read it (spec: unit-scheduling).
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline.unit_store import Cause
from agent_build_kit.pipeline.units import IN_REVIEW, PLANNED
from agent_build_kit.pipeline.workspaces import branch_lock
from tests.emergency_lane_support import build, fresh
from tests.lane_run_slots import Slots

pytestmark = pytest.mark.usefixtures("scripted_engine")


def test_a_unit_in_flight_and_stored_running_and_a_lane_unit_stored_running_count_once_each(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    units = [build("flight/1"), build("both/1"), build("review/1", IN_REVIEW)]
    with Slots(tmp_path, monkeypatch, units, flagged=["both/1", "review/1"]) as slots:
        slots.run("both/1", "review/1")

        # `both/1` is in flight, stored running and in the lane; `review/1` is only in the lane.
        found = slots.occupancy(["flight/1", "both/1"])

        assert found == {"flight/1", "both/1", "review/1"}


def test_a_stored_running_unit_with_no_lane_and_no_flag_is_counted_as_before(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with Slots(tmp_path, monkeypatch, [build("held/1"), fresh("r1/1")]) as slots:
        assert slots.occupancy() == {"held/1"}


def test_a_lane_unit_stored_running_that_waits_behind_the_lanes_cap_is_not_counted_until_it_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    units = [build("run1/1"), build("run2/1"), fresh("r1/1"), fresh("r2/1")]
    with Slots(tmp_path, monkeypatch, units, cap=2, restacks=1, flagged=["run1/1", "run2/1"]) as s:
        s.run("run1/1")
        s.hand_over("run2/1")
        assert s.lanes.waiting == ["run2/1"]

        assert s.occupancy() == {"run1/1"}
        assert len(s.started()) == 1

        s.end("run1/1")
        assert s.runs.begun["run2/1"].wait(5)

        assert s.occupancy() == {"run2/1"}


def test_a_waiting_lane_unit_whose_branch_is_held_still_takes_no_slot_from_a_ready_unit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    units = [build("run1/1"), build("run2/1"), fresh("r1/1"), fresh("r2/1")]
    with Slots(tmp_path, monkeypatch, units, cap=2, restacks=1, flagged=["run1/1", "run2/1"]) as s:
        s.run("run1/1")
        s.hand_over("run2/1")
        assert s.lanes.waiting == ["run2/1"]

        # Not idle: a lock is held on its branch, so only the lane's wait leaves it out.
        with branch_lock("spec/run2/1", root=s.inst.state_dir / "locks"):
            assert s.occupancy() == {"run1/1"}
            assert len(s.started()) == 1


def test_a_planned_unit_the_lane_is_moving_reads_as_ready_not_as_waiting_for_a_slot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    units = [build("moved/1", PLANNED), fresh("r1/1")]
    with Slots(tmp_path, monkeypatch, units) as slots:
        slots.store.set_state("moved/1", PLANNED, branch="spec/moved/1", cause=Cause.BASE_CHANGED)
        slots.run("moved/1")

        slots.started()

        assert slots.reasons()["moved/1"] not in ("slot", "queue_full")


def test_a_planned_unit_waiting_in_the_lane_reads_as_ready_not_as_waiting_for_a_slot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    units = [build("run1/1"), build("moved/1", PLANNED), fresh("r1/1")]
    with Slots(tmp_path, monkeypatch, units, restacks=1, flagged=["run1/1"]) as slots:
        slots.store.set_state("moved/1", PLANNED, branch="spec/moved/1", cause=Cause.BASE_CHANGED)
        slots.run("run1/1")
        slots.hand_over("moved/1")
        assert slots.lanes.waiting == ["moved/1"]

        slots.started()

        assert slots.reasons()["moved/1"] not in ("slot", "queue_full")


def test_the_occupancy_is_counted_for_each_project_so_a_full_one_starts_nothing_and_another_does(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    units = [
        build("b1/1"),
        build("run1/1"),
        fresh("app-ready/1"),
        build("p1/1", repo="platform"),
        fresh("platform-ready/1", repo="platform"),
    ]
    with Slots(tmp_path, monkeypatch, units, cap=2, flagged=["run1/1"]) as slots:
        slots.run("run1/1")

        assert slots.occupancy(["b1/1", "p1/1"], of="b1/1") == {"b1/1", "run1/1"}
        assert slots.occupancy(["b1/1", "p1/1"], of="p1/1") == {"p1/1"}
        assert slots.started(["b1/1", "p1/1"]) == ["platform-ready/1"]


def test_the_lanes_admission_owed_units_and_the_scan_return_the_same_at_the_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ran: list[str] = []
    scanned = threading.Event()

    def run(inst: Any, unit: Any, **kwargs: Any) -> bool:
        ran.append(unit.id)
        scanned.set()
        return True

    monkeypatch.setattr(cli, "build_unit", run)
    builds = [f"b{n}/1" for n in range(1, 5)]
    units = [*(build(uid) for uid in builds), build("run1/1"), build("run2/1")]
    with Slots(tmp_path, monkeypatch, units, flagged=["run1/1", "run2/1"]) as slots:
        owed = cli.owed_units(slots.inst, slots.store.all())

        slots.run("run1/1")  # admitted with four builds in flight
        slots.lanes.scan(slots.store.all())  # and the scan takes `run2/1` beside it
        assert scanned.wait(5)

        assert {"run1/1", "run2/1"} <= owed
        assert ran == ["run2/1"]
        assert slots.occupancy(builds) >= {*builds, "run1/1"}
