"""A moved-base run in the lane counts toward the slot occupancy of its project and is never
refused or delayed for want of a free build worker; no build, new or resumed, starts while the
occupancy is at or above `max_concurrent_stacks` (spec: unit-scheduling).

The lane is a real one over runs that block until the test ends them (`tests/lane_run_slots.py`);
a round is `run_round` over the store, with the builds in flight named by the test.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.pipeline.units import IN_REVIEW
from tests.emergency_lane_support import build, fresh
from tests.lane_run_slots import Slots

pytestmark = pytest.mark.usefixtures("scripted_engine")


def builds(count: int) -> list[str]:
    return [f"b{n}/1" for n in range(1, count + 1)]


def test_a_run_beside_one_build_leaves_two_free_workers_and_ready_units_start_in_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    units = [build("b1/1"), build("run1/1"), fresh("r1/1"), fresh("r2/1"), fresh("r3/1")]
    with Slots(tmp_path, monkeypatch, units, flagged=["run1/1"]) as slots:
        slots.run("run1/1")

        assert slots.occupancy(["b1/1"]) == {"b1/1", "run1/1"}
        assert len(slots.started(["b1/1"])) == 2


def test_a_run_handed_over_beside_four_builds_starts_at_once_and_the_occupancy_reads_five(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    units = [*(build(uid) for uid in builds(4)), build("run1/1"), fresh("r1/1")]
    with Slots(tmp_path, monkeypatch, units, flagged=["run1/1"]) as slots:
        slots.run("run1/1")

        assert slots.lanes.running == ["run1/1"]
        assert slots.occupancy(builds(4)) == {*builds(4), "run1/1"}
        assert slots.started(builds(4)) == []


def test_no_build_new_or_resumed_starts_beside_three_builds_and_a_run_and_one_does_without_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # `res/1` is running with a thread and no run holding it: a resume, as `r1/1` is a start.
    units = [*(build(uid) for uid in builds(3)), build("run1/1"), build("res/1"), fresh("r1/1")]
    with Slots(tmp_path, monkeypatch, units, flagged=["run1/1"]) as slots:
        slots.run("run1/1")

        assert slots.started(builds(3)) == []

        slots.end("run1/1")

        assert len(slots.started(builds(3))) == 1


def test_one_build_ending_beside_four_builds_and_two_runs_leaves_five_and_starts_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    units = [
        *(build(uid) for uid in builds(4)),
        build("run1/1"),
        build("run2/1"),
        fresh("r1/1"),
    ]
    with Slots(tmp_path, monkeypatch, units, flagged=["run1/1", "run2/1"]) as slots:
        slots.run("run1/1", "run2/1")
        assert len(slots.occupancy(builds(4))) == 6

        slots.store.set_state("b4/1", IN_REVIEW, pr=9)

        assert slots.occupancy(builds(3)) == {*builds(3), "run1/1", "run2/1"}
        assert slots.started(builds(3)) == []
