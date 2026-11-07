"""What a person's assignment or block on the board does to the units that build it (spec:
tracker-pull)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from agent_build_kit import trackers
from agent_build_kit.pipeline.units import UnitState
from tests.trackers.apply_support import PERSON_NAME, AppliedBoard, building


@pytest.fixture(autouse=True)
def registered_kind() -> Iterator[None]:
    yield
    trackers.unregister("azure_devops")


def test_a_person_on_a_running_units_group_item_holds_it_by_name(tmp_path: Path) -> None:
    run = AppliedBoard(tmp_path, ["change", "group"], [building("lane-dedupe/1", 1)])

    run.board.assign_as_person(run.item_id("1"))
    run.apply()

    held = run.unit("lane-dedupe/1")
    assert held.state == UnitState.HELD
    assert f"assigned to {PERSON_NAME}" in held.note


def test_clearing_the_assignment_releases_the_hold(tmp_path: Path) -> None:
    run = AppliedBoard(tmp_path, ["change", "group"], [building("lane-dedupe/1", 1)])
    run.board.assign_as_person(run.item_id("1"))
    run.apply()

    run.board.person().set_assignee(run.item_id("1"), "")
    run.apply()

    assert run.unit("lane-dedupe/1").state != UnitState.HELD


def test_a_unit_covering_two_groups_is_held_when_only_the_second_is_assigned(
    tmp_path: Path,
) -> None:
    run = AppliedBoard(tmp_path, ["change", "group"], [building("lane-dedupe/1", 1, 2)])

    run.board.assign_as_person(run.item_id("2"))
    run.apply()

    held = run.unit("lane-dedupe/1")
    assert held.state == UnitState.HELD
    assert f"assigned to {PERSON_NAME}" in held.note


def test_a_person_on_a_task_item_under_the_group_item_holds_the_unit(tmp_path: Path) -> None:
    run = AppliedBoard(tmp_path, ["change", "group", "task"], [building("lane-dedupe/1", 1)])

    run.board.assign_as_person(run.item_id("1.2"))
    run.apply()

    held = run.unit("lane-dedupe/1")
    assert held.state == UnitState.HELD
    assert f"assigned to {PERSON_NAME}" in held.note


def test_a_person_on_a_task_item_of_another_units_group_holds_only_that_unit(
    tmp_path: Path,
) -> None:
    units = [building("lane-dedupe/1", 1), building("lane-dedupe/2", 2)]
    run = AppliedBoard(tmp_path, ["change", "group", "task"], units)

    run.board.assign_as_person(run.item_id("2.1"))
    run.apply()

    assert run.unit("lane-dedupe/2").state == UnitState.HELD
    assert run.unit("lane-dedupe/1").state == UnitState.RUNNING


def test_a_group_item_moved_to_blocked_holds_its_unit_and_unblocking_releases_it(
    tmp_path: Path,
) -> None:
    run = AppliedBoard(tmp_path, ["change", "group"], [building("lane-dedupe/1", 1)])

    run.board.person().update(run.item_id("1"), {"state": "blocked"})
    run.apply()
    held = run.unit("lane-dedupe/1")
    assert held.state == UnitState.HELD
    assert "blocked" in held.note

    run.board.person().update(run.item_id("1"), {"state": "active"})
    run.apply()
    assert run.unit("lane-dedupe/1").state != UnitState.HELD


def test_a_merged_unit_is_not_held_and_the_change_is_recorded(tmp_path: Path) -> None:
    merged = building("lane-dedupe/1", 1, state=UnitState.MERGED)
    run = AppliedBoard(tmp_path, ["change", "group"], [merged])

    run.board.assign_as_person(run.item_id("1"))
    applied = run.apply()

    assert run.unit("lane-dedupe/1").state == UnitState.MERGED
    assert applied.recorded
