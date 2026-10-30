"""The `Tests: required — <reason>` line of a group, and the mode `abk tags` shows."""

import argparse
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline.work_graph import GroupMode, validate_tasks
from tests.factories import planning

OPT_OUT = "Acceptance: none — a fixture about the Tests line\n"
DOC_TASK = "- [ ] 1.1 Describe the setting in `docs/cli.md`.\n"


def write(folder: Path, body: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "tasks.md"
    path.write_text(f"# Tasks\n\n{OPT_OUT}\n## 1. [app] [unit-test] Describe it\n\n{body}")
    return path


def test_required_with_a_reason_raises_a_documents_group_to_the_code_floor(
    tmp_path: Path,
) -> None:
    path = write(tmp_path, f"{DOC_TASK}\nTests: required — the setting keeps the disk bounded\n")

    groups, errors = validate_tasks(path)

    assert errors == []
    assert groups[0].mode is GroupMode.TESTS_AND_CODE


@pytest.mark.parametrize(
    "line",
    [
        "Tests: required - the setting keeps the disk bounded",
        "Tests: required -- the setting keeps the disk bounded",
        "Tests: required \N{EN DASH} the setting keeps the disk bounded",
        "tests: Required \N{EM DASH} the setting keeps the disk bounded",
        "TESTS: REQUIRED \N{EM DASH} the setting keeps the disk bounded",
    ],
)
def test_the_dash_and_the_case_of_the_line_do_not_matter(line: str, tmp_path: Path) -> None:
    groups, errors = validate_tasks(write(tmp_path, f"{DOC_TASK}\n{line}\n"))

    assert errors == []
    assert groups[0].mode is GroupMode.TESTS_AND_CODE


@pytest.mark.parametrize("line", ["Tests: required \N{EM DASH}", "Tests: required \N{EM DASH}   "])
def test_a_dash_with_an_empty_reason_is_an_error(line: str, tmp_path: Path) -> None:
    _, errors = validate_tasks(write(tmp_path, f"{DOC_TASK}\n{line}\n"))

    assert any("Tests:" in error.message and "reason" in error.message for error in errors)


def test_the_line_without_a_reason_is_an_error(tmp_path: Path) -> None:
    path = write(tmp_path, f"{DOC_TASK}\nTests: required\n")

    _, errors = validate_tasks(path)

    assert any("Tests:" in error.message and "reason" in error.message for error in errors)


def test_a_group_without_the_line_stays_no_code(tmp_path: Path) -> None:
    groups, errors = validate_tasks(write(tmp_path, DOC_TASK))

    assert errors == []
    assert groups[0].mode is GroupMode.NO_CODE


def test_abk_tags_reports_a_line_without_a_reason(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    inst = planning(tmp_path)
    write(inst.changes_dir / "feature", f"{DOC_TASK}\nTests: required\n")

    code = cli.cmd_tags(argparse.Namespace(all=False, change="feature"), inst)

    assert code == 1
    out = capsys.readouterr().out
    assert "Tests:" in out and "reason" in out


def test_abk_tags_shows_the_floor_mode_of_each_group(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    inst = planning(tmp_path)
    write(inst.changes_dir / "feature", f"{DOC_TASK}\nTests: required — another file reads it\n")

    code = cli.cmd_tags(argparse.Namespace(all=False, change="feature"), inst)

    assert code == 0
    group_line = next(
        line for line in capsys.readouterr().out.splitlines() if line.strip().startswith("1.")
    )
    assert GroupMode.TESTS_AND_CODE.value in group_line
