"""The per-task reader of `tasks.md`: each task with its key, full text and box state, agreeing
with the group parser on counts and leaving the plan digest alone (spec: tracker-mapping)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline.work_graph import read_tasks, validate_tasks
from tests.progress_support import copy_file, planning, tick, write_repository

OPT_OUT = "Acceptance: none — a fixture about the reader\n"

TWO_GROUPS = """\
# Tasks

## 1. [app] [unit-test] First

- [x] 1.1 Test: one, which
      continues on a second line.
- [ ] 1.2 Do one.

## 2. [app] [unit-test] Second

- [ ] 2.1 Do two.
"""

WITH_FLAGS = """\
# Tasks

## 1. [app] [unit-test] First

Priority: 2

- [ ] 1.1 Test: one.
- [ ] 1.2 Do one.

## 2. [app] [unit-test] Second

Needs: first group 1 — the first builds it
Priority: 1

- [x] 2.1 Test: two.
      Verify: red.
- [ ] 2.2 Do two.
- [ ] 2.3 Last.
"""

ENDED_BY_BLANK = """\
# Tasks

## 1. [app] [unit-test] First

- [ ] 1.1 Test: one,
      wrapped.

      Not part of the task.
- [ ] 1.2 Do one.
## 2. [app] [unit-test] Second

- [ ] 2.1 Do two.
"""

MISNUMBERED = """\
# Tasks

## 1. [app] [unit-test] First

- [ ] 1.1 Do one.

## 2. [app] [unit-test] Second

- [ ] 1.3 Copied from the group above.
- [ ] 2.2 Do two.
"""

ABOVE_FIRST_HEADING = """\
# Tasks

- [ ] 1.1 Belongs to no group.

## 1. [app] [unit-test] First

- [ ] 1.1 Do one.
"""

FIXTURES = {
    "two": TWO_GROUPS,
    "flags": WITH_FLAGS,
    "blank": ENDED_BY_BLANK,
    "misnumbered": MISNUMBERED,
    "above-first-heading": ABOVE_FIRST_HEADING,
}


def write(tmp_path: Path, text: str) -> Path:
    tasks = tmp_path / "tasks.md"
    tasks.write_text(text.replace("# Tasks\n\n", f"# Tasks\n\n{OPT_OUT}\n", 1))
    return tasks


def test_tasks_come_with_keys_text_and_box_states(tmp_path: Path) -> None:
    tasks = read_tasks(write(tmp_path, TWO_GROUPS), "feature")

    assert [t.key for t in tasks] == ["feature:1.1", "feature:1.2", "feature:2.1"]
    assert [t.done for t in tasks] == [True, False, False]
    assert [(t.group, t.number) for t in tasks] == [(1, 1), (1, 2), (2, 1)]
    assert "continues on a second line." in tasks[0].text
    assert tasks[0].text.startswith("Test: one, which")
    assert tasks[1].text == "Do one."


def test_a_blank_line_a_heading_or_the_next_task_ends_a_task(tmp_path: Path) -> None:
    tasks = read_tasks(write(tmp_path, ENDED_BY_BLANK), "feature")

    assert [t.key for t in tasks] == ["feature:1.1", "feature:1.2", "feature:2.1"]
    assert "wrapped." in tasks[0].text
    assert "Not part of the task." not in tasks[0].text
    assert tasks[1].text == "Do one.", "the heading after it is not a continuation"
    assert tasks[2].text == "Do two."


@pytest.mark.parametrize("name", FIXTURES)
def test_the_per_group_counts_equal_the_group_parser_s(tmp_path: Path, name: str) -> None:
    path = write(tmp_path, FIXTURES[name])
    groups, errors = validate_tasks(path)
    assert errors == []

    tasks = read_tasks(path, "feature")

    for group in groups:
        assert sum(1 for t in tasks if t.group == group.number) == group.task_count


def test_a_task_belongs_to_the_group_whose_heading_it_sits_under(tmp_path: Path) -> None:
    tasks = read_tasks(write(tmp_path, MISNUMBERED), "feature")

    assert [t.key for t in tasks] == ["feature:1.1", "feature:2.3", "feature:2.2"]
    assert [t.group for t in tasks] == [1, 2, 2]


def test_a_task_above_the_first_heading_is_left_out(tmp_path: Path) -> None:
    tasks = read_tasks(write(tmp_path, ABOVE_FIRST_HEADING), "feature")

    assert [t.key for t in tasks] == ["feature:1.1"]
    assert tasks[0].text == "Do one."


def test_reading_and_ticking_leave_the_plan_digest_unchanged(tmp_path: Path) -> None:
    inst = planning(tmp_path)
    path = write_repository(inst, "feature", write(tmp_path, WITH_FLAGS).read_text())
    before = cli.plan_digest(path)
    text = path.read_text()

    read_tasks(path, "feature")
    tick(inst, "feature", (2,), done=True)
    ticked = read_tasks(copy_file(inst, "feature"), "feature")

    assert [t.done for t in ticked if t.group == 2] == [True, True, True]
    assert cli.plan_digest(path) == before
    assert path.read_text() == text, "the repository file is not ticked"
    assert cli.plan_digest(copy_file(inst, "feature")) == before
