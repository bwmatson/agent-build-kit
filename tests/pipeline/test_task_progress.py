"""Ticking a unit's tasks off — by the pipeline, in a copy under the state directory."""

from pathlib import Path

import pytest

from agent_build_kit.pipeline.task_progress import (
    append_task,
    first_line_hash,
    rewrite_task,
    without_boxes,
)
from agent_build_kit.pipeline.work_graph import read_tasks
from tests.progress_support import (
    TASKS,
    copy_file,
    planning,
    repository_file,
    tick,
    write_repository,
)

CHANGE = "add-marker"


def test_a_unit_s_groups_are_ticked_and_nothing_else(tmp_path: Path) -> None:
    inst = planning(tmp_path)
    write_repository(inst, CHANGE, TASKS)

    tick(inst, CHANGE, (2,), done=True)

    assert repository_file(inst, CHANGE).read_text() == TASKS, "ticks go to the copy only"
    text = copy_file(inst, CHANGE).read_text()
    assert "- [x] 2.1 Test: two" in text
    assert "- [x] 2.10 Do two" in text
    assert "- [ ] 1.2 Do one" in text
    assert "- [ ] 12.1 Not group" in text, "2 is not a prefix match for 12"


def test_the_repository_file_is_left_byte_for_byte(tmp_path: Path) -> None:
    inst = planning(tmp_path)
    write_repository(inst, CHANGE, TASKS)
    before = repository_file(inst, CHANGE).read_bytes()

    tick(inst, CHANGE, (1, 2), done=True)
    tick(inst, CHANGE, (1,), done=False)

    assert repository_file(inst, CHANGE).read_bytes() == before


def test_a_failed_unit_s_groups_are_unticked(tmp_path: Path) -> None:
    inst = planning(tmp_path)
    write_repository(inst, CHANGE, TASKS)

    tick(inst, CHANGE, (1,), done=False)

    assert "- [ ] 1.1 Test: one" in copy_file(inst, CHANGE).read_text()
    assert repository_file(inst, CHANGE).read_text() == TASKS, "the repository file is untouched"


def test_the_text_of_a_task_is_never_changed(tmp_path: Path) -> None:
    inst = planning(tmp_path)
    write_repository(inst, CHANGE, TASKS)

    tick(inst, CHANGE, (1, 2), done=True)
    tick(inst, CHANGE, (1, 2), done=False)

    assert copy_file(inst, CHANGE).read_text() == TASKS.replace("- [x] 1.1", "- [ ] 1.1")


def test_the_copy_is_made_from_a_repository_file_that_already_has_ticks(tmp_path: Path) -> None:
    inst = planning(tmp_path)
    write_repository(inst, CHANGE, TASKS)

    tick(inst, CHANGE, (2,), done=True)

    text = copy_file(inst, CHANGE).read_text()
    assert "- [x] 1.1 Test: one" in text, "the tick the repository file carried seeds the copy"
    assert "- [x] 2.1 Test: two" in text


def test_without_boxes_of_the_copy_is_that_of_the_repository_file(tmp_path: Path) -> None:
    inst = planning(tmp_path)
    write_repository(inst, CHANGE, TASKS)

    tick(inst, CHANGE, (1, 2), done=True)

    assert without_boxes(copy_file(inst, CHANGE).read_text()) == without_boxes(TASKS)
    assert copy_file(inst, CHANGE).read_text() != TASKS


def test_a_rewrite_with_a_blank_line_in_the_body_keeps_the_whole_text_in_the_task(
    tmp_path: Path,
) -> None:
    tasks = tmp_path / "tasks.md"
    tasks.write_text("# Tasks\n\n## 1. [app] [unit-test] First\n\n- [ ] 1.1 Old\n- [ ] 1.2 Next\n")

    stored = rewrite_task(
        tasks, f"{CHANGE}:1.1", text="Do X\n\nVerify: Y", text_hash=first_line_hash("Old")
    )

    [first, second] = read_tasks(tasks, CHANGE)
    assert first.text == stored == "Do X\nVerify: Y"
    assert second.text == "Next"
    assert tasks.read_text().count("Verify: Y") == 1
    assert "\n      \n" not in tasks.read_text()


def test_an_appended_task_with_a_blank_line_in_the_text_is_read_back_whole(
    tmp_path: Path,
) -> None:
    tasks = tmp_path / "tasks.md"
    tasks.write_text("# Tasks\n\n## 1. [app] [unit-test] First\n\n- [ ] 1.1 Old\n")

    number, stored = append_task(tasks, CHANGE, 1, "Do X\n\nVerify: Y")

    assert number == 2
    assert stored == "Do X\nVerify: Y"
    assert [task.text for task in read_tasks(tasks, CHANGE)] == ["Old", stored]


def test_a_blank_text_is_refused_and_writes_nothing(tmp_path: Path) -> None:
    tasks = tmp_path / "tasks.md"
    text = "# Tasks\n\n## 1. [app] [unit-test] First\n\n- [ ] 1.1 Old\n"
    tasks.write_text(text)

    with pytest.raises(ValueError):
        rewrite_task(tasks, f"{CHANGE}:1.1", text=" \n ", text_hash=first_line_hash("Old"))
    with pytest.raises(ValueError):
        append_task(tasks, CHANGE, 1, "")

    assert tasks.read_text() == text
