"""The round's evaluation: a ready priority-0 unit starts past the workers and the places, the
lane's unit counts toward the occupancy so ordinary starts wait, and the restack lane is
admitted whatever the emergency lane's use.

Five places, four workers and an emergency lane of one, in a single project."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline.unit_store import Cause
from agent_build_kit.pipeline.units import IN_REVIEW, MERGED, PLANNED
from agent_build_kit.pipeline.vocabulary import WaitReason
from tests.emergency_lane_support import build, fresh, lane_workspace, seeded, started_by_round
from tests.factories import stored_unit
from tests.restack_lane_fakes import repo_behind
from tests.tick_pass import isolate

pytestmark = pytest.mark.usefixtures("scripted_engine")


@pytest.fixture(autouse=True)
def quiet(monkeypatch: pytest.MonkeyPatch) -> None:
    isolate(monkeypatch)


def runs(count: int) -> list[str]:
    return [f"run{n}/1" for n in range(count)]


def test_a_ready_priority_zero_unit_starts_past_the_workers_and_an_ordinary_one_does_not(
    tmp_path: Path,
) -> None:
    inst = lane_workspace(tmp_path)
    store = seeded(
        inst,
        tmp_path,
        [
            *(build(uid) for uid in runs(4)),
            build("rev/1", IN_REVIEW),
            fresh("one/1", priority=1),
            fresh("zero/1", priority=0),
        ],
    )

    assert started_by_round(inst, store, building=runs(4)) == ["zero/1"]


def test_a_second_priority_zero_unit_waits_for_the_lane_with_the_queue_full_reason(
    tmp_path: Path,
) -> None:
    inst = lane_workspace(tmp_path)
    units = [
        *(build(uid) for uid in runs(4)),
        build("rev/1", IN_REVIEW),
        fresh("zero/1", priority=0),
        fresh("zero/2", priority=0),
    ]
    store = seeded(inst, tmp_path, units)

    assert started_by_round(inst, store, building=runs(4)) == ["zero/1"]

    asked = cli.wait_reasons(
        inst, store.all(), started={"zero/1"}, building={*runs(4), "zero/1"}, only=frozenset()
    )
    assert asked["zero/2"].reason is WaitReason.QUEUE_FULL


def test_a_lane_unit_keeps_ordinary_starts_waiting_until_the_figures_fall_below_the_limits(
    tmp_path: Path,
) -> None:
    inst = lane_workspace(tmp_path)
    units = [
        *(build(uid) for uid in runs(4)),
        build("lane/1", priority=0),
        fresh("one/1", priority=1),
    ]
    store = seeded(inst, tmp_path, units, lane=["lane/1"])
    in_flight = {*runs(4), "lane/1"}
    assert started_by_round(inst, store, building=in_flight) == []

    store.set_state("run0/1", MERGED, pr=1)
    in_flight.discard("run0/1")
    # Four are still building, one of them the lane's: the occupancy is at the cap.
    assert started_by_round(inst, store, building=in_flight) == []

    store.set_state("run1/1", MERGED, pr=2)
    in_flight.discard("run1/1")
    assert started_by_round(inst, store, building=in_flight) == ["one/1"]


def test_a_unit_owed_a_restack_is_admitted_whatever_the_emergency_lane_holds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inst = repo_behind(tmp_path, monkeypatch, emergency_extra=1)
    owed = "feature/3"
    units = [
        *(build(uid) for uid in runs(3)),
        build("lane/1", priority=0),
        (stored_unit(owed, change="feature", branch="spec/feature/3"), PLANNED),
        fresh("zero/2", priority=0),
    ]
    store = seeded(inst, tmp_path, units, lane=["lane/1"])
    store.set_state(owed, PLANNED, branch="spec/feature/3", cause=Cause.BASE_CHANGED)
    in_flight = {*runs(3), "lane/1"}

    asked = cli.wait_reasons(inst, store.all(), started=set(), building=in_flight, only=frozenset())

    assert asked[owed].reason is WaitReason.READY
    assert asked["zero/2"].reason is WaitReason.QUEUE_FULL
    assert started_by_round(inst, store, building=in_flight) == []
