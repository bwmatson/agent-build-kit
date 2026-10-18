"""A group is in one split; a test which must run in two splits is written as two groups."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.pipeline.work_graph import TaskGroup, ValidationError, validate_tasks
from tests.split_workspace import group, line_of, splits_workspace, tasks_text


def read(tmp_path: Path, text: str) -> tuple[list[TaskGroup], list[ValidationError]]:
    (tmp_path / "tasks.md").write_text(text)
    return validate_tasks(tmp_path / "tasks.md")


def assert_one_split_rule(error: ValidationError) -> None:
    assert "a group is in one split" in error.message
    assert "two groups" in error.message


def test_a_second_split_line_in_a_group_is_refused_at_the_second_line(tmp_path: Path) -> None:
    splits_workspace(tmp_path / "planning")
    text = tasks_text(group(1, "Split: acp", "Split: claude_code"))

    _, errors = read(tmp_path, text)

    (error,) = errors
    assert error.line == line_of(text, "Split: claude_code")
    assert_one_split_rule(error)


@pytest.mark.parametrize("value", ["claude_code, acp", "claude_code acp", "claude_code,acp"])
def test_a_line_naming_more_than_one_split_is_refused_with_the_same_instruction(
    tmp_path: Path, value: str
) -> None:
    splits_workspace(tmp_path / "planning")
    text = tasks_text(group(1, f"Split: {value}"))

    _, errors = read(tmp_path, text)

    (error,) = errors
    assert error.line == line_of(text, f"Split: {value}")
    assert_one_split_rule(error)


def test_nothing_is_split_or_kept_of_a_refused_line(tmp_path: Path) -> None:
    splits_workspace(tmp_path / "planning")
    text = tasks_text(group(1, "Split: claude_code, acp"), group(2, "Split: acp", "Split: rest"))

    groups, errors = read(tmp_path, text)

    assert len(errors) == 2
    assert {g.split for g in groups} <= {"rest"}
