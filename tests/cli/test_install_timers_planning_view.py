"""`abk install-timers` checks the `.planning` link and never makes it."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit import timers
from agent_build_kit.cli import main
from agent_build_kit.config import dump
from tests.loginctl_fake import Loginctl, SubprocessModule
from tests.planning_worktree_support import installation_at, working_copy_of


@pytest.fixture
def state(tmp_path: Path) -> Path:
    path = tmp_path / "state-home" / "state"
    path.mkdir(parents=True)
    return path


@pytest.fixture
def working_copy(tmp_path: Path, state: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A working copy that is its own planning root, whose state directory is `state`."""
    _, repo = working_copy_of(tmp_path / "repos")
    config = installation_at(repo, repo, planning={"state_dir": str(state)}).config
    (repo / "abk.yaml").write_text(dump(config))
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(timers, "user_unit_dir", lambda: tmp_path / "units")
    monkeypatch.setattr(timers, "subprocess", SubprocessModule(Loginctl("yes")))
    monkeypatch.chdir(repo)
    return repo


def notes(out: str) -> list[str]:
    return [line for line in out.splitlines() if ".planning" in line and "abk init" in line]


def test_a_missing_link_is_not_made_and_a_note_names_abk_init(
    working_copy: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["install-timers"]) == 0

    assert not (working_copy / ".planning").is_symlink()
    assert not (working_copy / ".planning").exists()
    assert notes(capsys.readouterr().out)


def test_a_link_to_the_wrong_place_is_left_and_noted_and_a_right_one_is_not(
    working_copy: Path, state: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (working_copy / ".planning").symlink_to(elsewhere)

    assert main(["install-timers"]) == 0

    assert (working_copy / ".planning").readlink() == elsewhere
    assert notes(capsys.readouterr().out)

    (working_copy / ".planning").unlink()
    (working_copy / ".planning").symlink_to(state)

    assert main(["install-timers"]) == 0

    assert not notes(capsys.readouterr().out)


def test_a_state_inside_the_repository_is_not_checked_for_a_link(
    working_copy: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    inside = str(working_copy / "runs")
    config = installation_at(working_copy, working_copy, planning={"state_dir": inside}).config
    (working_copy / "abk.yaml").write_text(dump(config))

    assert main(["install-timers"]) == 0

    assert not notes(capsys.readouterr().out)
