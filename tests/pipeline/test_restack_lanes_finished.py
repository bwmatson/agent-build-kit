"""Waiting on the lanes of a workspace: `finished()` and `drain()` cover every lane, and a lane
nothing has touched is not made."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from agent_build_kit.pipeline.restack_lane import RestackLanes
from tests.restack_lane_fakes import WAIT, Restacks
from tests.restack_lanes_fakes import API, WEB, Made, unit_of


@pytest.fixture
def restacks() -> Restacks:
    return Restacks()


@pytest.fixture
def made(tmp_path: Path, restacks: Restacks) -> Made:
    return Made(tmp_path / "locks", restacks)


@pytest.fixture
def lanes(made: Made, restacks: Restacks) -> Iterator[RestackLanes]:
    with RestackLanes(made, owed=lambda units: made.owed) as lanes:
        yield lanes
        restacks.release_all()
        lanes.drain()


def test_finished_completes_when_the_next_restack_of_any_lane_ends(
    lanes: RestackLanes, restacks: Restacks
) -> None:
    lanes.hand_over(unit_of(1, WEB))
    lanes.hand_over(unit_of(2, API))
    assert restacks.begun["feature/1"].wait(WAIT)
    assert restacks.begun["feature/2"].wait(WAIT)
    ends = lanes.finished()
    assert not ends.done()

    restacks.release("feature/2")

    ends.result(timeout=WAIT)
    assert restacks.finished == ["feature/2"]
    assert lanes.running == ["feature/1"]


def test_finished_is_complete_at_once_when_no_lane_has_work(
    lanes: RestackLanes, restacks: Restacks
) -> None:
    assert lanes.finished().done()

    lanes.hand_over(unit_of(1, WEB))
    restacks.release_all()
    lanes.drain()

    assert lanes.finished().done()


def test_drain_returns_when_every_lane_is_idle(lanes: RestackLanes, restacks: Restacks) -> None:
    for number in (1, 2, 3, 4, 5):
        lanes.hand_over(unit_of(number, WEB if number % 2 else API))
    restacks.release_all()

    lanes.drain()

    assert sorted(restacks.finished) == [f"feature/{number}" for number in (1, 2, 3, 4, 5)]
    assert lanes.running == lanes.waiting == []


def test_a_lane_for_a_project_nothing_has_touched_is_not_made(
    lanes: RestackLanes, made: Made
) -> None:
    lanes.scan([unit_of(1, WEB), unit_of(2, API)])
    assert lanes.finished().done()
    assert lanes.running == lanes.waiting == []

    assert made.by_project == {}

    lanes.hand_over(unit_of(3, WEB))

    assert set(made.by_project) == {WEB}
