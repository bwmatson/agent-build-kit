"""The `Priority:` line in a change's tasks.md.

A group carries a priority from 1 (most urgent) to 5, 3 when it says nothing; a
line above the first group is the change's default and a group's own line wins.
"""

import argparse
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.work_graph import TaskGroup, ValidationError, validate_tasks
from tests.conftest import make_installation

OPT_OUT = "Acceptance: none — a fixture about priorities\n"


def tasks_md(*priorities: str | None, head: str = "") -> str:
    """A change with one group per entry, each carrying that `Priority:` value
    (none for a group without the line); `head` is written above the first group."""
    text = f"# Tasks\n\n{OPT_OUT}{head}\n"
    for number, value in enumerate(priorities, start=1):
        text += f"## {number}. [app] [tier1] Group {number}\n\n"
        text += f"Priority: {value}\n\n" if value is not None else ""
        text += f"- [ ] {number}.1 Test: it.\n- [ ] {number}.2 Do it.\n\n"
    return text


def read(text: str, tmp_path: Path) -> tuple[list[TaskGroup], list[ValidationError]]:
    (tmp_path / "tasks.md").write_text(text)
    return validate_tasks(tmp_path / "tasks.md")


def priority_errors(errors: list[ValidationError]) -> list[int]:
    return [e.line for e in errors if "riority" in e.message]


def test_a_group_sets_its_own_priority(tmp_path: Path) -> None:
    groups, errors = read(tasks_md("2", None), tmp_path)

    assert errors == []
    assert [g.priority for g in groups] == [2, 3]


def test_a_group_with_no_line_and_no_default_is_normal(tmp_path: Path) -> None:
    groups, errors = read(tasks_md(None, None), tmp_path)

    assert errors == []
    assert [g.priority for g in groups] == [3, 3]


def test_a_line_above_the_first_group_is_the_changes_default(tmp_path: Path) -> None:
    groups, errors = read(tasks_md(None, None, head="Priority: 4\n"), tmp_path)

    assert errors == []
    assert [g.priority for g in groups] == [4, 4]


def test_a_groups_own_line_wins_over_the_default(tmp_path: Path) -> None:
    groups, errors = read(tasks_md(None, "2", None, head="Priority: 4\n"), tmp_path)

    assert errors == []
    assert [g.priority for g in groups] == [4, 2, 4]


@pytest.mark.parametrize("value", [1, 2, 3, 4, 5])
def test_every_value_on_the_scale_is_read(tmp_path: Path, value: int) -> None:
    groups, errors = read(tasks_md(str(value)), tmp_path)

    assert errors == []
    assert groups[0].priority == value


@pytest.mark.parametrize("value", ["0", "6", "-1", "high", "2.5", "two", "1 2"])
def test_a_value_outside_the_scale_is_reported_with_its_line(tmp_path: Path, value: str) -> None:
    text = tasks_md(value)
    line = text.splitlines().index(f"Priority: {value}") + 1

    _, errors = read(text, tmp_path)

    assert priority_errors(errors) == [line]


@pytest.mark.parametrize("value", ["0", "6", "high", "2.5"])
def test_a_bad_default_is_reported_with_its_line(tmp_path: Path, value: str) -> None:
    text = tasks_md(None, head=f"Priority: {value}\n")
    line = text.splitlines().index(f"Priority: {value}") + 1

    _, errors = read(text, tmp_path)

    assert priority_errors(errors) == [line]


def test_a_second_line_in_one_group_is_reported_at_the_second(tmp_path: Path) -> None:
    text = tasks_md("2").replace("Priority: 2\n", "Priority: 2\nPriority: 1\n")
    second = text.splitlines().index("Priority: 1") + 1

    _, errors = read(text, tmp_path)

    assert priority_errors(errors) == [second]


def test_a_second_default_above_the_first_group_is_reported(tmp_path: Path) -> None:
    text = tasks_md(None, head="Priority: 4\nPriority: 2\n")
    second = text.splitlines().index("Priority: 2") + 1

    _, errors = read(text, tmp_path)

    assert priority_errors(errors) == [second]


def test_a_line_in_a_group_the_reader_cannot_parse_is_reported(tmp_path: Path) -> None:
    """Under a heading that did not parse there is no group to attach it to."""
    text = tasks_md("2") + "## 2. [no-such-repo] [tier1] Group 2\n\nPriority: 1\n\n- [ ] 2.1 x\n"
    line = text.splitlines().index("Priority: 1") + 1

    _, errors = read(text, tmp_path)

    assert line in priority_errors(errors)


def test_a_change_without_the_line_is_read_as_before(tmp_path: Path) -> None:
    groups, errors = read(tasks_md(None), tmp_path)

    assert errors == []
    assert [(g.number, g.repo, g.tier, g.task_count) for g in groups] == [(1, "app", "tier1", 2)]
    assert groups[0].priority == 3


def write_change(tmp_path: Path, text: str) -> Installation:
    inst = make_installation(tmp_path)
    path = inst.changes_dir / "feature"
    path.mkdir(parents=True)
    (path / "tasks.md").write_text(text)
    return inst


def test_abk_tags_lists_a_priority_that_is_not_normal(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    inst = write_change(tmp_path, tasks_md("2", "3", None))

    status = cli.cmd_tags(argparse.Namespace(change="feature", all=False), inst)

    lines = capsys.readouterr().out.splitlines()
    assert status == 0
    assert "priority 2" in next(line for line in lines if "Group 1" in line).lower()
    assert "priority" not in next(line for line in lines if "Group 2" in line).lower()
    assert "priority" not in next(line for line in lines if "Group 3" in line).lower()


def test_abk_tags_refuses_a_bad_priority_and_names_the_line(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    text = tasks_md("6")
    inst = write_change(tmp_path, text)
    line = text.splitlines().index("Priority: 6") + 1

    status = cli.cmd_tags(argparse.Namespace(change="feature", all=False), inst)

    assert status == 1
    assert f"line {line}:" in capsys.readouterr().out
