"""A unit that is finishing is never held back by the emergency lane: a rework runs at a full
project, and a resume is held to the free workers counted without the lane's unit."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline import emergency_lane
from agent_build_kit.pipeline.units import PLANNED
from tests.emergency_lane_support import build, lane_workspace, seeded, started_by_round
from tests.tick_pass import isolate

pytestmark = pytest.mark.usefixtures("scripted_engine")


@pytest.fixture(autouse=True)
def quiet(monkeypatch: pytest.MonkeyPatch) -> None:
    isolate(monkeypatch)
    monkeypatch.setattr(cli, "has_thread", lambda inst, unit_id: unit_id == "paused/1")


def normal(count: int) -> list[str]:
    return [f"run{n}/1" for n in range(count)]


def test_a_rework_is_returned_while_a_priority_zero_unit_runs_in_the_lane_at_a_full_project(
    tmp_path: Path,
) -> None:
    inst = lane_workspace(tmp_path)
    store = seeded(
        inst,
        tmp_path,
        [
            *(build(uid) for uid in normal(3)),
            build("lane/1", priority=0),
            build("rework/1", PLANNED, pr=7),
        ],
        lane=["lane/1"],
    )

    assert started_by_round(inst, store, building={*normal(3), "lane/1"}) == ["rework/1"]


def test_a_paused_unit_is_resumed_with_three_normal_builds_and_the_lane_unit(
    tmp_path: Path,
) -> None:
    inst = lane_workspace(tmp_path)
    store = seeded(
        inst,
        tmp_path,
        [*(build(uid) for uid in normal(3)), build("lane/1", priority=0), build("paused/1")],
        lane=["lane/1"],
    )

    assert started_by_round(inst, store, building={*normal(3), "lane/1"}) == ["paused/1"]


def test_a_paused_unit_waits_with_four_normal_builds_and_the_lane_unit(tmp_path: Path) -> None:
    inst = lane_workspace(tmp_path)
    store = seeded(
        inst,
        tmp_path,
        [*(build(uid) for uid in normal(4)), build("lane/1", priority=0), build("paused/1")],
        lane=["lane/1"],
    )
    in_flight = {*normal(4), "lane/1"}

    assert "lane/1" in emergency_lane.lane_units(inst.state_dir)
    assert started_by_round(inst, store, building=in_flight) == []
