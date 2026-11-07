"""What a person's edits to task items on the board do to `tasks.md`: boxes, text and appended
tasks, written only through the pipeline (spec: tracker-pull)."""

from __future__ import annotations

import inspect
from collections.abc import Iterator
from pathlib import Path

import pytest

from agent_build_kit import trackers
from agent_build_kit.pipeline.planner import parse_plan
from agent_build_kit.pipeline.task_progress import first_line_hash
from agent_build_kit.pipeline.tracker_file import read_tracker
from agent_build_kit.pipeline.units import UnitState
from agent_build_kit.pipeline.work_graph import read_tasks, validate_tasks
from agent_build_kit.trackers import apply
from tests.cli.replan_driver import answer, planned
from tests.trackers.apply_support import AppliedBoard, building
from tests.trackers.board_support import CHANGE, TASKS

LEVELS = ["change", "group", "task"]
EDITED = "Add the report in `src/app/report.py` and print it. Verify: 2.1 passes."
ADDED = "Check the lanes twice"


@pytest.fixture(autouse=True)
def registered_kind() -> Iterator[None]:
    yield
    trackers.unregister("azure_devops")


def test_a_task_item_done_on_the_board_ticks_only_its_box(tmp_path: Path) -> None:
    run = AppliedBoard(tmp_path, LEVELS)

    run.board.person().update(run.item_id("2.1"), {"state": "done"})
    run.apply()

    assert run.tasks.read_text() == TASKS.replace("- [ ] 2.1 ", "- [x] 2.1 ")


def test_a_reopened_task_item_unticks_its_box(tmp_path: Path) -> None:
    run = AppliedBoard(tmp_path, LEVELS)

    run.board.person().update(run.item_id("1.1"), {"state": "new"})
    run.apply()

    assert run.tasks.read_text() == TASKS.replace("- [x] 1.1 ", "- [ ] 1.1 ")


def test_edited_text_rewrites_that_tasks_lines_and_updates_its_hash(tmp_path: Path) -> None:
    run = AppliedBoard(tmp_path, LEVELS)
    original = [line for line in TASKS.splitlines() if line.startswith("- [ ] 2.2 ")][0]

    run.board.person().update(run.item_id("2.2"), {"title": EDITED, "body": EDITED})
    run.apply()

    assert run.tasks.read_text() == TASKS.replace(original, f"- [ ] 2.2 {EDITED}")
    recorded = read_tracker(run.world.change_dir)
    assert recorded is not None
    assert recorded.tasks[f"{CHANGE}:2.2"].text_hash == first_line_hash(EDITED)


def test_editing_a_two_line_task_replaces_both_of_its_lines(tmp_path: Path) -> None:
    run = AppliedBoard(tmp_path, LEVELS)
    both = (
        "- [ ] 1.2 Add the fill in `src/app/lanes.py`, covered by `tests/lanes/test_conflict.py`.\n"
        "      Verify: 1.1 passes.\n"
    )
    assert both in TASKS

    run.board.person().update(run.item_id("1.2"), {"title": EDITED, "body": EDITED})
    run.apply()

    assert run.tasks.read_text() == TASKS.replace(both, f"- [ ] 1.2 {EDITED}\n")


def test_a_task_added_with_only_a_title_survives_being_marked_done(tmp_path: Path) -> None:
    run = AppliedBoard(tmp_path, LEVELS, [building("lane-dedupe/1", 1, 2)])
    added = run.board.person().create("task", ADDED, "", parent=run.item_id("1"))
    run.apply()

    run.board.person().update(added.id, {"state": "done"})
    applied = run.apply()

    assert f"- [x] 1.3 {ADDED}\n" in run.tasks.read_text()
    assert applied.conflicts == ()
    recorded = read_tracker(run.world.change_dir)
    assert recorded is not None
    assert recorded.tasks[f"{CHANGE}:1.3"].fields["state"] == "done"


def test_a_board_body_with_a_blank_line_is_written_whole_into_the_task(tmp_path: Path) -> None:
    run = AppliedBoard(tmp_path, LEVELS)
    body = "Do X\n\nVerify: Y"

    run.board.person().update(run.item_id("2.2"), {"title": "Do X", "body": body})
    run.apply()

    [task] = [t for t in read_tasks(run.tasks, CHANGE) if t.key == f"{CHANGE}:2.2"]
    assert task.text == "Do X\nVerify: Y"
    assert run.tasks.read_text().count("Verify: Y") == 1


def test_a_task_edited_to_nothing_on_the_board_is_a_conflict_and_nothing_is_written(
    tmp_path: Path,
) -> None:
    run = AppliedBoard(tmp_path, LEVELS)

    run.board.person().update(run.item_id("2.2"), {"title": "", "body": ""})
    applied = run.apply()

    assert run.tasks.read_text() == TASKS
    assert [conflict.item_id for conflict in applied.conflicts] == [run.item_id("2.2")]


def test_a_failed_read_of_the_board_during_holds_still_records_the_ticked_task(
    tmp_path: Path,
) -> None:
    run = AppliedBoard(tmp_path, LEVELS, [building("lane-dedupe/1", 2)])
    group = run.item_id("2")
    run.board.fail = lambda call: (
        RuntimeError("the board timed out")
        if call.name == "get" and call.args[0] == group
        else None
    )

    run.board.person().update(run.item_id("2.1"), {"state": "done"})
    run.apply()

    assert "- [x] 2.1 " in run.tasks.read_text()
    recorded = read_tracker(run.world.change_dir)
    assert recorded is not None
    assert recorded.tasks[f"{CHANGE}:2.1"].fields["state"] == "done"


def test_a_task_also_edited_in_the_spec_is_a_conflict_and_nothing_is_written(
    tmp_path: Path,
) -> None:
    run = AppliedBoard(tmp_path, LEVELS)
    in_spec = TASKS.replace("Add the report in", "Add the whole report in")
    run.tasks.write_text(in_spec)

    run.board.person().update(run.item_id("2.2"), {"title": EDITED, "body": EDITED})
    applied = run.apply()

    assert run.tasks.read_text() == in_spec
    [conflict] = applied.conflicts
    assert conflict.item_id == run.item_id("2.2")
    assert "Add the whole report in" in conflict.spec_value
    assert conflict.tracker_value == EDITED


def test_a_task_added_under_a_group_item_is_appended_unticked_to_the_lowest_covered_group(
    tmp_path: Path,
) -> None:
    run = AppliedBoard(tmp_path, LEVELS, [building("lane-dedupe/1", 1, 2)])

    added = run.board.person().create("task", ADDED, "", parent=run.item_id("2"))
    run.apply()

    assert run.tasks.read_text() == TASKS.replace(
        "      Verify: 1.1 passes.\n", f"      Verify: 1.1 passes.\n- [ ] 1.3 {ADDED}\n"
    )
    recorded = read_tracker(run.world.change_dir)
    assert recorded is not None
    assert recorded.tasks[f"{CHANGE}:1.3"].id == added.id


def test_an_item_under_a_level_whose_child_is_absent_attaches_to_the_level_below(
    tmp_path: Path,
) -> None:
    run = AppliedBoard(tmp_path, ["change", "task"], [building("lane-dedupe/1", 1, 2)])

    added = run.board.person().create("task", ADDED, "", parent=run.world.item_id(CHANGE))
    run.apply()

    assert f"- [ ] 1.3 {ADDED}" in run.tasks.read_text()
    recorded = read_tracker(run.world.change_dir)
    assert recorded is not None
    assert recorded.tasks[f"{CHANGE}:1.3"].id == added.id


def test_an_item_with_no_level_below_is_a_conflict_and_adds_no_line(tmp_path: Path) -> None:
    run = AppliedBoard(tmp_path, ["change", "group"], [building("lane-dedupe/1", 1, 2)])

    added = run.board.person().create("task", ADDED, "", parent=run.item_id("1"))
    applied = run.apply()

    assert run.tasks.read_text() == TASKS
    [conflict] = applied.conflicts
    assert conflict.item_id == added.id
    assert "no level to join" in conflict.note


def test_a_started_unit_keeps_its_id_and_branch_after_a_task_is_appended(tmp_path: Path) -> None:
    # The unit builds group 1 alone: an e2e-test group (2) always has a unit of its own.
    started = building("lane-dedupe/1", 1)
    run = AppliedBoard(tmp_path, LEVELS, [started])

    run.board.person().create("task", ADDED, "", parent=run.item_id("1"))
    run.apply()

    text = run.tasks.read_text()
    assert text != TASKS
    groups, _ = validate_tasks(run.tasks)
    plan = parse_plan(
        answer(planned("lane-dedupe/1", (1,)), planned("lane-dedupe/2", (2,))),
        groups=groups,
        change=CHANGE,
        tasks=text,
    )
    run.store.upsert(list(plan.units), change=CHANGE)
    kept = run.unit("lane-dedupe/1")
    assert kept.branch == "spec/lane-dedupe/1"
    assert kept.state == UnitState.RUNNING


def test_the_apply_step_writes_the_planning_files_only_through_the_pipelines_functions() -> None:
    source = inspect.getsource(apply)

    assert "mark_task" in source
    for direct in ("write_text", "write_bytes", "atomic_write_text", "open(", "yaml.safe_dump"):
        assert direct not in source, f"the apply step writes with {direct} itself"
