"""A moved-base run in the lane: the entry owns no claim, holds one of the lane's workers for
the whole run, and a branch held by another run leaves the unit owed (spec: unit-scheduling).

The run's work is a fake that blocks on an event, so what runs beside what is read from the
order things happened in, never from the clock.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

from agent_build_kit.pipeline.events import build_claim
from agent_build_kit.pipeline.restack_lane import RestackLane
from agent_build_kit.pipeline.unit_store import StoredUnit
from agent_build_kit.pipeline.units import branch_name
from agent_build_kit.pipeline.workspaces import branch_lock
from tests.restack_lane_fakes import WAIT, Events, units


class Claims:
    """The lane's claim over the real branch locks, noting each unit it is asked for."""

    def __init__(self, locks: Path) -> None:
        self.asked: list[str] = []
        self._claim = build_claim(locks)

    def __call__(self, unit: StoredUnit):
        self.asked.append(unit.id)
        return self._claim(unit)


class Runs:
    """The work of each run: it notes its thread, starts, and ends in `ending` once released."""

    def __init__(self, ending: type[BaseException] | None = None) -> None:
        self.ending = ending
        self.started: list[str] = []
        self.threads: dict[str, str] = {}
        self.begun = Events()
        self.released = Events()
        self.mutex = threading.Lock()

    def of(self, unit: StoredUnit):
        def run() -> None:
            with self.mutex:
                self.started.append(unit.id)
                self.threads[unit.id] = threading.current_thread().name
            self.begun[unit.id].set()
            assert self.released[unit.id].wait(WAIT)
            if self.ending is not None:
                raise self.ending(unit.id)

        return run

    def release_all(self) -> None:
        for unit in units(9):
            self.released[unit.id].set()


@pytest.fixture
def locks(tmp_path: Path) -> Path:
    return tmp_path / "locks"


@pytest.fixture
def claims(locks: Path) -> Claims:
    return Claims(locks)


@pytest.fixture
def runs() -> Runs:
    return Runs()


@pytest.fixture
def lane(claims: Claims, runs: Runs) -> Iterator[RestackLane]:
    with RestackLane(2, move=lambda unit: None, claim=claims) as lane:
        yield lane
        runs.release_all()
        lane.drain()


def test_two_of_three_runs_start_and_the_third_starts_when_one_ends(
    lane: RestackLane, runs: Runs, claims: Claims
) -> None:
    first, second, third = units(3)
    for unit in (first, second, third):
        lane.hand_over(unit, runs.of(unit), claimed=False)

    assert runs.begun[first.id].wait(WAIT)
    assert runs.begun[second.id].wait(WAIT)
    assert lane.running == [first.id, second.id]
    assert lane.waiting == [third.id]

    runs.released[second.id].set()

    assert runs.begun[third.id].wait(WAIT)
    assert claims.asked == [], "the lane's entry owns no claim for a run"


@pytest.mark.parametrize("ending", [None, RuntimeError])
def test_a_run_holds_its_lane_worker_until_it_ends_however_it_ends(
    claims: Claims, ending: type[BaseException] | None
) -> None:
    runs = Runs(ending)
    first, second, _ = units(3)
    with RestackLane(1, move=lambda unit: None, claim=claims) as lane:
        lane.hand_over(first, runs.of(first), claimed=False)
        lane.hand_over(second, runs.of(second), claimed=False)
        assert runs.begun[first.id].wait(WAIT)

        assert lane.running == [first.id]
        assert lane.waiting == [second.id]
        assert not runs.begun[second.id].is_set()

        runs.released[first.id].set()
        assert runs.begun[second.id].wait(WAIT)
        runs.release_all()
        lane.drain()
    assert claims.asked == []


def test_a_run_goes_on_in_a_worker_of_the_lane(
    lane: RestackLane, runs: Runs, claims: Claims
) -> None:
    (unit,) = units(1)
    lane.hand_over(unit, runs.of(unit), claimed=False)

    assert runs.begun[unit.id].wait(WAIT)
    assert runs.threads[unit.id] == "restack"
    assert claims.asked == []


def test_a_unit_named_twice_is_queued_once(lane: RestackLane, runs: Runs, claims: Claims) -> None:
    first, second, third = units(3)
    lane.hand_over(first, runs.of(first), claimed=False)
    lane.hand_over(second, runs.of(second), claimed=False)
    lane.hand_over(third, runs.of(third), claimed=False)
    lane.hand_over(third, runs.of(third), claimed=False)

    assert lane.waiting == [third.id]
    runs.release_all()
    lane.drain()
    assert runs.started.count(third.id) == 1
    assert claims.asked == []


def test_a_branch_held_by_another_run_leaves_the_unit_owed_and_no_run_is_made(
    locks: Path, claims: Claims
) -> None:
    (unit,) = units(1)
    made: list[str] = []
    ended: list[bool] = []

    def run() -> None:
        with branch_lock(branch_name(unit), root=locks):
            made.append(unit.id)

    with RestackLane(2, move=lambda unit: None, claim=claims) as lane:
        with branch_lock(branch_name(unit), root=locks):
            lane.hand_over(unit, run, claimed=False, done=ended.append)
            lane.drain()

        assert made == []
        assert ended == [False]
        assert lane.running == lane.waiting == []

        lane.hand_over(unit, run, claimed=False)
        lane.drain()
        assert made == [unit.id], "owed still: the next hand over runs it"
