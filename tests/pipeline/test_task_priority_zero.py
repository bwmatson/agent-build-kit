"""`Priority: 0`, the emergency lane, in a change's tasks.md.

The scale is 0 (emergency) to 5; the lines 1 to 5 read as they always did, and
a value off the scale is refused with a message that names the range.
"""

from pathlib import Path

import pytest

from tests.task_priority_files import priority_errors, read, tasks_md


def test_a_group_may_be_priority_zero_and_one_with_no_line_is_normal(tmp_path: Path) -> None:
    groups, errors = read(tasks_md("0", None), tmp_path)

    assert errors == []
    assert [g.priority for g in groups] == [0, 3]


def test_a_default_of_zero_goes_to_groups_without_a_line_and_a_groups_own_line_wins(
    tmp_path: Path,
) -> None:
    groups, errors = read(tasks_md(None, "2", None, head="Priority: 0\n"), tmp_path)

    assert errors == []
    assert [g.priority for g in groups] == [0, 2, 0]


def test_every_line_from_one_to_five_reads_as_before_beside_a_zero(tmp_path: Path) -> None:
    groups, errors = read(tasks_md("1", "2", "3", "4", "5", "0"), tmp_path)

    assert errors == []
    assert [g.priority for g in groups] == [1, 2, 3, 4, 5, 0]


def test_a_second_line_after_a_zero_is_reported_at_the_second(tmp_path: Path) -> None:
    text = tasks_md("0").replace("Priority: 0\n", "Priority: 0\nPriority: 1\n")
    second = text.splitlines().index("Priority: 1") + 1

    _, errors = read(text, tmp_path)

    assert priority_errors(errors) == [second]


def test_a_second_default_after_a_zero_default_is_reported_at_the_second(tmp_path: Path) -> None:
    text = tasks_md(None, head="Priority: 0\nPriority: 2\n")
    second = text.splitlines().index("Priority: 2") + 1

    _, errors = read(text, tmp_path)

    assert priority_errors(errors) == [second]


def test_a_zero_in_a_group_the_reader_cannot_parse_is_the_existing_error(tmp_path: Path) -> None:
    text = tasks_md("2") + "## 2. [no-such-repo] [tier1] Group 2\n\nPriority: 0\n\n- [ ] 2.1 x\n"
    line = text.splitlines().index("Priority: 0") + 1

    _, errors = read(text, tmp_path)

    assert priority_errors(errors) == [line]
    assert "could not be read" in next(e.message for e in errors if e.line == line)


@pytest.mark.parametrize("value", ["6", "-1", "10", "2.5", "high"])
def test_a_value_off_the_scale_is_reported_with_its_line_and_names_zero_to_five(
    tmp_path: Path, value: str
) -> None:
    text = tasks_md(value)
    line = text.splitlines().index(f"Priority: {value}") + 1

    _, errors = read(text, tmp_path)

    assert priority_errors(errors) == [line]
    message = next(e.message for e in errors if e.line == line)
    assert "0" in message
    assert "5" in message
    assert "from 1" not in message
