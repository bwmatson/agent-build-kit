"""Writing one task's box by key, refused when the line no longer matches its recorded hash
(spec: tracker-mapping)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.pipeline.task_progress import TaskConflict, first_line_hash, mark_task

TASKS = """\
# Tasks

## 1. [app] [unit-test] First

- [ ] 1.1 Test: one
- [ ] 1.2 Test: two,
      which continues.
- [ ] 1.3 Do it
"""


def tasks_file(tmp_path: Path) -> Path:
    path = tmp_path / "tasks.md"
    path.write_text(TASKS)
    return path


def test_ticking_the_second_of_three_changes_only_its_box(tmp_path: Path) -> None:
    tasks = tasks_file(tmp_path)

    mark_task(tasks, "feature:1.2", done=True, text_hash=first_line_hash("Test: two,"))

    assert tasks.read_text() == TASKS.replace("- [ ] 1.2", "- [x] 1.2")


def test_a_ticked_box_can_be_unticked(tmp_path: Path) -> None:
    tasks = tasks_file(tmp_path)
    digest = first_line_hash("Test: one")
    mark_task(tasks, "feature:1.1", done=True, text_hash=digest)

    mark_task(tasks, "feature:1.1", done=False, text_hash=digest)

    assert tasks.read_text() == TASKS


def test_an_edited_line_is_not_written_and_the_conflict_names_the_key(tmp_path: Path) -> None:
    tasks = tasks_file(tmp_path)
    recorded = first_line_hash("Test: two,")
    edited = TASKS.replace("Test: two,", "Test: two, reworded")
    tasks.write_text(edited)

    with pytest.raises(TaskConflict, match="feature:1.2"):
        mark_task(tasks, "feature:1.2", done=True, text_hash=recorded)

    assert tasks.read_text() == edited


def test_the_hash_is_of_the_first_line_only() -> None:
    assert first_line_hash("Test: two,\nwhich continues.") == first_line_hash("Test: two,")
    assert first_line_hash("Test: two,") != first_line_hash("Test: one")
