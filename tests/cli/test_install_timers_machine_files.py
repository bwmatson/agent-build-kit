"""`abk install-timers` carries the machine files into the pipeline worktree and says so."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.cli import main
from tests.cli.install_timers_support import (
    add_worktree,
    publish_planning,
    worktree_of,
)
from tests.machine_files_support import CONTENT, give

ALL = (".env", "abk.local.yaml", "scrub.local")


def lines_of(capsys: pytest.CaptureFixture[str]) -> list[str]:
    return capsys.readouterr().out.splitlines()


def test_every_file_is_linked_and_a_line_says_so(
    working_copy: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    publish_planning(working_copy)
    give(working_copy, *ALL)

    assert main(["install-timers"]) == 0

    lines = lines_of(capsys)
    for name in ALL:
        link = worktree_of(tmp_path) / name
        assert any(line.startswith("linked") and str(link) in line for line in lines)
        assert link.is_symlink()
        assert link.read_text() == CONTENT[name]


def test_a_repeat_says_unchanged_for_every_file(
    working_copy: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    publish_planning(working_copy)
    give(working_copy, *ALL)
    assert main(["install-timers"]) == 0
    capsys.readouterr()

    assert main(["install-timers"]) == 0

    lines = lines_of(capsys)
    for name in ALL:
        link = worktree_of(tmp_path) / name
        assert any(line.startswith("unchanged") and str(link) in line for line in lines)
    assert not any(line.startswith("linked") for line in lines)


def test_a_different_file_in_the_worktree_exits_1_naming_it_and_writes_no_unit(
    working_copy: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    publish_planning(working_copy)
    give(working_copy, *ALL)
    mine = add_worktree(working_copy, tmp_path) / "abk.local.yaml"
    mine.write_text("planning: {self_pull: false}\n")

    assert main(["install-timers"]) == 1

    assert "abk.local.yaml" in capsys.readouterr().err
    assert mine.read_text() == "planning: {self_pull: false}\n"
    assert not mine.is_symlink()
    assert not (mine.parent / ".env").exists()
    assert list((tmp_path / "units").glob("*")) == []


def test_a_dry_run_says_would_link_and_makes_no_link(
    working_copy: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    publish_planning(working_copy)
    give(working_copy, *ALL)
    worktree = add_worktree(working_copy, tmp_path)

    assert main(["install-timers", "--dry-run"]) == 0

    lines = lines_of(capsys)
    for name in ALL:
        assert any(line.startswith("would link") and str(worktree / name) in line for line in lines)
        assert not (worktree / name).is_symlink()


def test_run_with_the_worktrees_config_the_files_are_linked_from_the_main_working_tree(
    working_copy: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    publish_planning(working_copy)
    give(working_copy, *ALL)
    worktree = add_worktree(working_copy, tmp_path)

    assert main(["--config", str(worktree / "abk.yaml"), "install-timers"]) == 0

    for name in ALL:
        assert (worktree / name).is_symlink()
        assert (worktree / name).resolve() == (working_copy / name).resolve()
    assert any(line.startswith("linked") for line in lines_of(capsys))


def test_a_working_copy_with_no_machine_file_exits_0_and_prints_no_link_line(
    working_copy: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    publish_planning(working_copy)

    assert main(["install-timers"]) == 0

    out = capsys.readouterr().out
    assert not any(word in line for line in out.splitlines() for word in ("linked", "would link"))
