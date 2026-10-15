"""`abk install-timers` from a planning repo that is also a code repo: what it tells the person.

The worktree the units run in is not where they are standing, so the command says where it is,
what the units' working directory is, and which `--config` reaches that installation from here.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit import timers
from agent_build_kit.cli import main
from agent_build_kit.config import dump
from tests.loginctl_fake import Loginctl, SubprocessModule
from tests.planning_worktree_support import installation_at, working_copy_of


@pytest.fixture
def working_copy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A working copy that is its own planning root, on a machine with its own home and units."""
    _, repo = working_copy_of(tmp_path / "repos")
    (repo / "abk.yaml").write_text(dump(installation_at(repo, repo).config))
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(timers, "user_unit_dir", lambda: tmp_path / "units")
    monkeypatch.setattr(timers, "subprocess", SubprocessModule(Loginctl("yes")))
    monkeypatch.chdir(repo)
    return repo


def worktree_of(tmp_path: Path) -> Path:
    return tmp_path / "home" / ".local" / "share" / "app" / "planning"


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
