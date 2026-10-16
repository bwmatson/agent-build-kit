"""The lanes of a workspace: a lane for each project, with a cap and a first-seen queue of
its own, so a full lane never holds back another project's restack."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from agent_build_kit.pipeline.restack_lane import RestackLanes
from tests.restack_lane_fakes import WAIT, Restacks
from tests.restack_lanes_fakes import API, DOCS, WEB, Made, unit_of

THREE_EACH = [(1, WEB), (2, API), (3, WEB), (4, API), (5, WEB), (6, API)]


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


def test_three_restacks_seen_in_each_of_two_projects_run_two_of_each_and_queue_one(
    lanes: RestackLanes, restacks: Restacks
) -> None:
    for number, key in THREE_EACH:
        lanes.hand_over(unit_of(number, key))

    for number in (1, 2, 3, 4):
        assert restacks.begun[f"feature/{number}"].wait(WAIT)
    assert sorted(lanes.running) == ["feature/1", "feature/2", "feature/3", "feature/4"]
    assert sorted(lanes.waiting) == ["feature/5", "feature/6"]


def test_a_waiting_restack_starts_when_a_restack_of_its_own_project_ends(
    lanes: RestackLanes, made: Made, restacks: Restacks
) -> None:
    for number, key in THREE_EACH:
        lanes.hand_over(unit_of(number, key))
    assert restacks.begun["feature/4"].wait(WAIT)

    restacks.release("feature/2")

    assert restacks.begun["feature/6"].wait(WAIT)
    assert made.by_project[WEB].waiting == ["feature/5"]


def test_a_unit_of_a_third_project_starts_at_once_while_the_other_two_are_full(
    lanes: RestackLanes, restacks: Restacks
) -> None:
    for number, key in THREE_EACH:
        lanes.hand_over(unit_of(number, key))

    lanes.hand_over(unit_of(7, DOCS))

    assert restacks.begun["feature/7"].wait(WAIT)
    assert "feature/7" in lanes.running


def test_a_restack_is_handed_to_no_lane_but_its_projects(
    lanes: RestackLanes, made: Made, restacks: Restacks
) -> None:
    for number, key in [(1, WEB), (2, API), (3, DOCS)]:
        lanes.hand_over(unit_of(number, key))
        assert restacks.begun[f"feature/{number}"].wait(WAIT)

    assert set(made.by_project) == {WEB, API, DOCS}
    assert [made.by_project[key].running for key in (WEB, API, DOCS)] == [
        ["feature/1"],
        ["feature/2"],
        ["feature/3"],
    ]
