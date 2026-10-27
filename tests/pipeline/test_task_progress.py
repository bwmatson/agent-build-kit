"""Ticking a unit's tasks off — by the pipeline, in a copy under the state directory."""

from pathlib import Path

from agent_build_kit.pipeline.task_progress import without_boxes
from tests.progress_support import (
    TASKS,
    copy_file,
    planning,
    repository_file,
    tick,
    write_repository,
)

CHANGE = "add-marker"


def test_a_unit_s_groups_are_ticked_in_the_copy_and_nothing_else(tmp_path: Path) -> None:
    inst = planning(tmp_path)
    write_repository(inst, CHANGE, TASKS)

    tick(inst, CHANGE, (2,), done=True)

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


def test_a_failed_unit_s_groups_are_unticked_in_the_copy(tmp_path: Path) -> None:
    inst = planning(tmp_path)
    write_repository(inst, CHANGE, TASKS)

    tick(inst, CHANGE, (1,), done=False)

    assert "- [ ] 1.1 Test: one" in copy_file(inst, CHANGE).read_text()


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
