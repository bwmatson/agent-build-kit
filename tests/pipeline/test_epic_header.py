"""The `Epic:` line in a change's tasks.md header: the manual parent a change names."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.work_graph import epic_reference
from tests.conftest import make_installation
from tests.task_priority_files import read, tasks_md

TITLE = "Agent Assessment: P0 Foundation"


def write_change(tmp_path: Path, text: str) -> tuple[Installation, Path]:
    inst = make_installation(tmp_path)
    folder = inst.changes_dir / "feature"
    folder.mkdir(parents=True)
    (folder / "tasks.md").write_text(text)
    return inst, folder / "tasks.md"


def test_an_id_is_read(tmp_path: Path) -> None:
    _, tasks = write_change(tmp_path, tasks_md(None, head="Epic: 259\n"))

    assert epic_reference(tasks) == "259"


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
    text = tasks_md(None, head="Epic: 259\nEpic: 260\n")
    line = text.splitlines().index("Epic: 260") + 1

    _, errors = read(text, tmp_path)

    assert [e.line for e in errors if "Epic" in e.message] == [line]


@pytest.mark.parametrize("edit", [None, "Epic: 300", f"Epic: {TITLE}"])
def test_the_line_never_moves_the_plan_hash(tmp_path: Path, edit: str | None) -> None:
    inst, tasks = write_change(tmp_path, tasks_md(None, head="Epic: 259\n"))
    before = cli.plan_digest(tasks, inst=inst)

    tasks.write_text(tasks_md(None, head=f"{edit}\n" if edit else ""))

    assert cli.plan_digest(tasks, inst=inst) == before


def test_abk_tags_accepts_a_change_with_the_line(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    inst, tasks = write_change(tmp_path, tasks_md(None, head="Epic: 259\n"))

    status = cli.cmd_tags(argparse.Namespace(change="feature", all=False), inst)

    assert status == 0, capsys.readouterr().out
    assert epic_reference(tasks) == "259"
