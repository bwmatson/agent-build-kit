"""A removal or a title edit on the board is recorded and never applied, and the manual epic is
left alone (spec: tracker-pull)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from agent_build_kit import trackers
from tests.trackers.apply_support import AppliedBoard
from tests.trackers.board_support import CHANGE, TASKS

LEVELS = ["change", "group", "task"]


@pytest.fixture(autouse=True)
def registered_kind() -> Iterator[None]:
    yield
    trackers.unregister("azure_devops")


def item_of(run: AppliedBoard, level: str) -> str:
    """The board item of the change, of group 1 or of task 2.2."""
    return {
        "change": run.world.item_id(CHANGE),
        "group": run.item_id("1"),
        "task": run.item_id("2.2"),
    }[level]


@pytest.mark.parametrize("level", ["change", "group", "task"])
def test_an_item_removed_on_the_board_is_a_conflict_and_leaves_the_spec_alone(
    tmp_path: Path, level: str
) -> None:
    run = AppliedBoard(tmp_path, LEVELS)
    removed = item_of(run, level)

    run.board.person().update(removed, {"state": "removed"})
    applied = run.apply()

    assert run.tasks.read_text() == TASKS
    assert [(c.item_id, c.field) for c in applied.conflicts] == [(removed, "removed")]
    assert [(c.item_id, c.field) for c in run.open_conflicts()] == [(removed, "removed")]


@pytest.mark.parametrize("level", ["change", "group", "task"])
def test_an_item_removed_on_the_board_is_not_recreated_by_the_outbound_pass(
    tmp_path: Path, level: str
) -> None:
    run = AppliedBoard(tmp_path, LEVELS)
    removed = item_of(run, level)
    run.board.person().update(removed, {"state": "removed"})
    run.apply()
    before = len(run.board.calls)

    run.world.run()

    after = run.board.calls[before:]
    assert [call for call in after if call.name == "create"] == []
    assert [c.item_id for c in run.open_conflicts()] == [removed]
    assert run.board.get(removed).state == "removed"
    assert [call for call in after if call.name == "update" and call.args[0] == removed] == []


def test_restoring_a_removed_item_closes_its_conflict(tmp_path: Path) -> None:
    run = AppliedBoard(tmp_path, LEVELS)
    removed = run.item_id("1")
    run.board.person().update(removed, {"state": "removed"})
    run.apply()
    assert len(run.open_conflicts()) == 1

    run.board.person().update(removed, {"state": "new"})
    run.apply()

    assert run.open_conflicts() == []
    assert run.tasks.read_text() == TASKS


@pytest.mark.parametrize("level", ["change", "group"])
def test_a_title_edited_on_the_board_is_recorded_and_the_spec_title_stays(
    tmp_path: Path, level: str
) -> None:
    run = AppliedBoard(tmp_path, LEVELS)
    edited = item_of(run, level)
    original = run.board.get(edited).title

    run.board.person().update(edited, {"title": "A title a person chose"})
    applied = run.apply()

    assert run.tasks.read_text() == TASKS
    [conflict] = applied.conflicts
    assert (conflict.item_id, conflict.field) == (edited, "title")
    assert (conflict.spec_value, conflict.tracker_value) == (original, "A title a person chose")
    assert [(c.item_id, c.field) for c in run.open_conflicts()] == [(edited, "title")]


@pytest.mark.parametrize("level", ["change", "group"])
def test_the_next_outbound_pass_restores_a_title_edited_on_the_board(
    tmp_path: Path, level: str
) -> None:
    run = AppliedBoard(tmp_path, LEVELS)
    edited = item_of(run, level)
    original = run.board.get(edited).title
    run.board.person().update(edited, {"title": "A title a person chose"})
    run.apply()

    run.world.run()

    assert run.board.get(edited).title == original


@pytest.mark.parametrize("closed", ["done", "removed"])
def test_the_epic_is_never_reconciled_and_a_closed_one_is_a_single_warning(
    tmp_path: Path, closed: str
) -> None:
    run = AppliedBoard(tmp_path, ["change", "group"], epic=True)
    epic = run.epic_id
    change_item = run.world.item_id(CHANGE)
    change_before = run.board.get(change_item)

    run.board.person().update(epic, {"title": "Retitled by a person"})
    run.board.person().set_assignee(epic, "alice@example.test")
    applied = run.apply()

    assert applied.conflicts == ()
    assert run.open_conflicts() == []
    assert [line for line in run.world.logs if epic in line and CHANGE in line] == []

    run.board.person().update(epic, {"state": closed})
    run.apply()
    run.board.person().update(epic, {"tags": "again"})
    run.apply()
    run.board.person().update(epic, {"tags": "and again"})
    applied = run.apply()

    warnings = [line for line in run.world.logs if epic in line and CHANGE in line]
    assert len(warnings) == 1
    assert applied.conflicts == ()
    assert run.open_conflicts() == []
    assert run.board.get(change_item) == change_before
    assert [call for call in run.board.writes() if call.args and call.args[0] == epic] == []
