"""`abk config --migrate` shows the diff, asks, and writes only on a yes."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.cli import main
from agent_build_kit.runtimes.policy_apply import BACKUP_SUFFIX
from tests.cli.config_migrate_fakes import OLD, beside, run_migrate, write


def test_a_yes_prints_the_diff_first_then_writes_and_names_the_backup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write(tmp_path)

    code, terminal = run_migrate(capsys, monkeypatch, path, answers=("y",))

    assert code == 0
    assert terminal.asked == 1
    assert "project_limits" in terminal.shown[0]
    assert "max_concurrent_stacks" in terminal.shown[0]
    assert "global_limits:" in path.read_text()
    assert path.read_text() != OLD
    backup = path.with_name(path.name + BACKUP_SUFFIX)
    assert backup.read_text() == OLD
    assert str(backup) in terminal.out


def test_a_no_writes_nothing_makes_no_backup_and_exits_1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write(tmp_path)

    code, terminal = run_migrate(capsys, monkeypatch, path, answers=("n",))

    assert code == 1
    assert terminal.asked == 1
    assert path.read_text() == OLD
    assert beside(path) == []


def test_no_terminal_and_no_yes_writes_nothing_and_exits_1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write(tmp_path)

    code, _ = run_migrate(capsys, monkeypatch, path, answers=None, piped="y\n")

    assert code == 1
    assert path.read_text() == OLD
    assert beside(path) == []


def test_yes_asks_nothing_and_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write(tmp_path)

    code, terminal = run_migrate(capsys, monkeypatch, path, "--yes")

    assert code == 0
    assert terminal.asked == 0
    assert "project_limits" in terminal.out
    assert "project_limits:" in path.read_text()
    assert path.with_name(path.name + BACKUP_SUFFIX).read_text() == OLD


def test_yes_writes_with_no_terminal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write(tmp_path)

    code, _ = run_migrate(capsys, monkeypatch, path, "--yes", answers=None)

    assert code == 0
    assert "project_limits:" in path.read_text()


def test_dry_run_prints_the_diff_writes_nothing_and_exits_0(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write(tmp_path)

    code, terminal = run_migrate(capsys, monkeypatch, path, "--dry-run")

    assert code == 0
    assert terminal.asked == 0
    assert "project_limits" in terminal.out
    assert path.read_text() == OLD
    assert beside(path) == []


@pytest.mark.parametrize("flag", ["--yes", "--dry-run"])
def test_yes_and_dry_run_need_migrate(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], flag: str
) -> None:
    path = write(tmp_path)

    code = main(["--config", str(path), "config", flag])

    assert code == 2
    assert "need --migrate" in capsys.readouterr().err
    assert path.read_text() == OLD
