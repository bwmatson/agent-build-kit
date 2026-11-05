"""The resolution lane, the restack lane under its new name: a cap, a first-seen queue with a unit
once, and a worker thread named "resolve"."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

from agent_build_kit.pipeline.events import build_claim
from agent_build_kit.pipeline.resolution_lane import ResolutionLane
from agent_build_kit.pipeline.unit_store import StoredUnit
from tests.factories import stored_unit
from tests.restack_lane_fakes import WAIT, Restacks, units


@pytest.fixture
def locks(tmp_path: Path) -> Path:
    return tmp_path / "locks"


@pytest.fixture
def runs() -> Restacks:
    return Restacks()


@pytest.fixture
def lane(locks: Path, runs: Restacks) -> Iterator[ResolutionLane]:
    lane = ResolutionLane(2, move=runs, claim=build_claim(locks))
    with lane:
        yield lane
        runs.release_all()
        lane.drain()


def test_two_of_five_runs_start_before_the_hand_over_returns(
    lane: ResolutionLane, runs: Restacks
) -> None:
    for unit in units(5):
        lane.hand_over(unit)

    assert runs.begun["feature/1"].wait(WAIT)
    assert runs.begun["feature/2"].wait(WAIT)
    assert lane.running == ["feature/1", "feature/2"]
    assert lane.waiting == ["feature/3", "feature/4", "feature/5"]


def test_each_waiting_run_starts_in_the_order_seen_as_one_finishes(
    lane: ResolutionLane, runs: Restacks
) -> None:
    for unit in units(4):
        lane.hand_over(unit)

    assert runs.begun["feature/2"].wait(WAIT)
    runs.release("feature/2")
    assert runs.begun["feature/3"].wait(WAIT)
    runs.release("feature/1")
    assert runs.begun["feature/4"].wait(WAIT)

    assert runs.started[2:] == ["feature/3", "feature/4"]
    assert runs.most_at_once == 2


def test_a_unit_named_twice_is_queued_once(lane: ResolutionLane, runs: Restacks) -> None:
    first, second, third = units(3)
    for unit in (first, second, third, third):
        lane.hand_over(unit)

    assert lane.waiting == ["feature/3"]
    runs.release_all()
    lane.drain()
    assert runs.started.count("feature/3") == 1


def test_a_run_goes_on_a_thread_named_resolve(locks: Path) -> None:
    names: list[str] = []

    def move(unit: StoredUnit) -> None:
        names.append(threading.current_thread().name)

    lane = ResolutionLane(2, move=move, claim=build_claim(locks))
    with lane:
        lane.hand_over(stored_unit("feature/1", change="feature"))
        lane.drain()

    assert names == ["resolve"]
