"""The `Epic:` line in a change's tasks.md header: the manual parent a change names."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.work_graph import epic_reference
from tests.conftest import make_installation
from tests.task_priority_files import read, tasks_md

TITLE = "Roadmap: Phase One"


def write_change(tmp_path: Path, text: str) -> tuple[Installation, Path]:
    inst = make_installation(tmp_path)
    folder = inst.changes_dir / "feature"
    folder.mkdir(parents=True)
    (folder / "tasks.md").write_text(text)
    return inst, folder / "tasks.md"


def in_a_group(line: str) -> str:
    """A change with the line as its own line inside its first group."""
    return tasks_md(None).replace("Group 1\n\n", f"Group 1\n\n{line}\n\n", 1)


def in_a_task(line: str) -> str:
    """A change with the line as the indented continuation of its first task."""
    return tasks_md(None).replace("1.1 Test: it.\n", f"1.1 Test: it.\n  {line}\n", 1)


def test_an_id_is_read(tmp_path: Path) -> None:
    _, tasks = write_change(tmp_path, tasks_md(None, head="Epic: 42\n"))

    assert epic_reference(tasks) == "42"


def test_an_exact_title_is_read_whole(tmp_path: Path) -> None:
    _, tasks = write_change(tmp_path, tasks_md(None, head=f"Epic: {TITLE}\n"))

    assert epic_reference(tasks) == TITLE


def test_a_change_with_no_line_names_no_epic(tmp_path: Path) -> None:
    _, tasks = write_change(tmp_path, tasks_md(None))

    assert epic_reference(tasks) is None


def test_a_line_with_no_value_is_a_tag_error_naming_the_line(tmp_path: Path) -> None:
    text = tasks_md(None, head="Epic:\n")
    line = text.splitlines().index("Epic:") + 1

    _, errors = read(text, tmp_path)

    assert [e.line for e in errors if "Epic" in e.message] == [line]


def test_a_second_line_is_a_tag_error_naming_it(tmp_path: Path) -> None:
    text = tasks_md(None, head="Epic: 42\nEpic: 43\n")
    line = text.splitlines().index("Epic: 43") + 1

    _, errors = read(text, tmp_path)

    assert [e.line for e in errors if "Epic" in e.message] == [line]


@pytest.mark.parametrize("edit", [None, "Epic: 44", f"Epic: {TITLE}"])
def test_the_line_never_moves_the_plan_hash(tmp_path: Path, edit: str | None) -> None:
    inst, tasks = write_change(tmp_path, tasks_md(None, head="Epic: 42\n"))
    before = cli.plan_digest(tasks, inst=inst)

    tasks.write_text(tasks_md(None, head=f"{edit}\n" if edit else ""))

    assert cli.plan_digest(tasks, inst=inst) == before


def test_abk_tags_accepts_a_change_with_the_line(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    inst, tasks = write_change(tmp_path, tasks_md(None, head="Epic: 42\n"))

    status = cli.cmd_tags(argparse.Namespace(change="feature", all=False), inst)

    assert status == 0, capsys.readouterr().out
    assert epic_reference(tasks) == "42"


@pytest.mark.parametrize("place", [in_a_group, in_a_task], ids=["group", "task"])
def test_a_line_below_the_first_group_names_no_epic(
    tmp_path: Path, place: Callable[[str], str]
) -> None:
    _, tasks = write_change(tmp_path, place("Epic: the header line in the example"))

    assert epic_reference(tasks) is None


@pytest.mark.parametrize("place", [in_a_group, in_a_task], ids=["group", "task"])
def test_a_line_below_the_first_group_is_a_tag_error_naming_the_line(
    tmp_path: Path, place: Callable[[str], str]
) -> None:
    text = place("Epic: 42")
    line = next(n for n, text_ in enumerate(text.splitlines(), 1) if "Epic: 42" in text_)

    _, errors = read(text, tmp_path)

    assert [e.line for e in errors if "Epic" in e.message] == [line]


@pytest.mark.parametrize("place", [in_a_group, in_a_task], ids=["group", "task"])
def test_editing_a_line_below_the_first_group_moves_the_plan_hash(
    tmp_path: Path, place: Callable[[str], str]
) -> None:
    inst, tasks = write_change(tmp_path, place("Epic: 42"))
    before = cli.plan_digest(tasks, inst=inst)

    tasks.write_text(place("Epic: 43"))

    assert cli.plan_digest(tasks, inst=inst) != before
