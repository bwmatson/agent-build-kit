"""`abk install-timers` from a planning repo that is also a code repo: what it tells the person.

The worktree the units run in is not where they are standing, so the command says where it is,
what the units' working directory is, and which `--config` reaches that installation from here.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from agent_build_kit.cli import main
from tests.cli.install_timers_support import worktree_of


def test_the_output_names_the_worktree_it_made(
    working_copy: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["install-timers"]) == 0

    lines = capsys.readouterr().out.splitlines()
    assert any("created" in line and str(worktree_of(tmp_path)) in line for line in lines)


def test_the_output_names_the_worktree_it_reused(
    working_copy: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["install-timers"]) == 0
    capsys.readouterr()

    assert main(["install-timers"]) == 0

    lines = capsys.readouterr().out.splitlines()
    assert any("reused" in line and str(worktree_of(tmp_path)) in line for line in lines)


def test_the_output_names_the_units_working_directory(
    working_copy: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["install-timers"]) == 0

    assert f"units point at {worktree_of(tmp_path)}" in capsys.readouterr().out


def test_the_output_gives_the_config_to_use_from_a_working_copy(
    working_copy: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["install-timers"]) == 0

    out = capsys.readouterr().out
    assert f"--config {worktree_of(tmp_path) / 'abk.yaml'}" in out


def test_remove_prints_the_worktree_it_left_and_the_command_that_removes_it(
    working_copy: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    worktree = worktree_of(tmp_path)
    assert main(["install-timers"]) == 0
    capsys.readouterr()

    assert main(["install-timers", "--remove"]) == 0

    out = capsys.readouterr().out
    assert str(worktree) in out
    assert f"git worktree remove {worktree}" in out
    assert worktree.is_dir()


def test_remove_says_so_when_the_marked_worktree_is_gone(
    working_copy: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    worktree = worktree_of(tmp_path)
    assert main(["install-timers"]) == 0
    shutil.rmtree(worktree)
    capsys.readouterr()

    assert main(["install-timers", "--remove"]) == 0

    out = capsys.readouterr().out
    assert "git worktree prune" in out
    assert f"git worktree remove {worktree}" not in out
