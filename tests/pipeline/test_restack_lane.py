"""The lane restacks run in: a cap, a first-seen queue with a unit once, and one restack
of a branch at a time."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from agent_build_kit.pipeline.restack_lane import RestackLane
from agent_build_kit.pipeline.unit_store import StoredUnit
from agent_build_kit.pipeline.workspaces import branch_lock
from tests.factories import stored_unit
from tests.restack_lane_fakes import WAIT, Restacks, lane_over, units


@pytest.fixture
def locks(tmp_path: Path) -> Path:
    return tmp_path / "locks"


@pytest.fixture
def restacks() -> Restacks:
    return Restacks()


@pytest.fixture
def lane(locks: Path, restacks: Restacks) -> Iterator[RestackLane]:
    with lane_over(locks, restacks, cap=2) as lane:
        yield lane
        restacks.release_all()
        lane.drain()


def test_two_of_five_restacks_start_before_the_hand_over_returns(
    lane: RestackLane, restacks: Restacks
) -> None:
    for unit in units(5):
        lane.hand_over(unit)

    assert restacks.started == ["feature/1", "feature/2"]
    assert lane.running == ["feature/1", "feature/2"]
    assert lane.waiting == ["feature/3", "feature/4", "feature/5"]


def test_each_waiting_restack_starts_in_the_order_seen_as_one_finishes(
    lane: RestackLane, restacks: Restacks
) -> None:
    for unit in units(5):
        lane.hand_over(unit)

    restacks.release("feature/2")
    assert restacks.begun["feature/3"].wait(WAIT)
    restacks.release("feature/1")
    assert restacks.begun["feature/4"].wait(WAIT)
    restacks.release("feature/3")
    assert restacks.begun["feature/5"].wait(WAIT)

    assert restacks.started == [f"feature/{number}" for number in range(1, 6)]
    assert restacks.most_at_once == 2


def test_a_unit_named_twice_is_queued_once(lane: RestackLane, restacks: Restacks) -> None:
    first, second, third = units(3)
    lane.hand_over(first)
    lane.hand_over(second)
    lane.hand_over(third)
    lane.hand_over(third)

    assert lane.waiting == ["feature/3"]
    restacks.release_all()
    lane.drain()
    assert restacks.started.count("feature/3") == 1


def test_a_unit_moves_onto_the_base_it_has_when_its_move_starts(locks: Path) -> None:
    bases = {"feature/3": "spec/feature/1"}
    seen: list[str] = []
    gate = Restacks()

    def move(unit: StoredUnit) -> None:
        if unit.id == "feature/3":
            seen.append(bases[unit.id])
        else:
            gate(unit)

    first, second, third = units(3)
    with lane_over(locks, move, cap=2) as lane:
        lane.hand_over(first)
        lane.hand_over(second)
        lane.hand_over(third)
        bases["feature/3"] = "main"
        lane.hand_over(third)
        gate.release_all()
        lane.drain()

    assert seen == ["main"]


def test_a_restack_that_finds_its_branch_claimed_leaves_the_unit_as_it_was(
    locks: Path, restacks: Restacks
) -> None:
    unit = stored_unit("feature/1", change="feature")
    with lane_over(locks, restacks, owed=lambda graph: ["feature/1"]) as lane:
        with branch_lock("spec/feature/1", root=locks):
            lane.hand_over(unit)
            lane.drain()

        assert restacks.started == []
        assert lane.running == []
        assert lane.waiting == []

        lane.scan([unit])
        restacks.release_all()
        lane.drain()

    assert restacks.finished == ["feature/1"]


def test_a_scan_does_not_retry_a_unit_while_the_holder_still_has_it(
    locks: Path, restacks: Restacks
) -> None:
    unit = stored_unit("feature/1", change="feature")
    with lane_over(locks, restacks, owed=lambda graph: ["feature/1"]) as lane:
        with branch_lock("spec/feature/1", root=locks):
            lane.scan([unit])
            lane.drain()
            assert restacks.started == []

        lane.scan([unit])
        assert restacks.begun["feature/1"].wait(WAIT)
        restacks.release_all()


def test_two_restacks_of_one_branch_never_overlap(lane: RestackLane, restacks: Restacks) -> None:
    unit = stored_unit("feature/1", change="feature")
    lane.hand_over(unit)
    assert restacks.begun["feature/1"].wait(WAIT)

    lane.hand_over(unit)
    lane.hand_over(stored_unit("feature/1", change="feature", title="the same unit, read again"))
    restacks.release_all()
    lane.drain()

    assert restacks.most_at_once == 1
