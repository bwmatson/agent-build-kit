"""`abk config --migrate` names the running units before it asks, and runs the existing steps
only for an abk.yaml git does not track."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from agent_build_kit.runtimes.policy_apply import BACKUP_SUFFIX
from tests.cli.config_migrate_fakes import OLD, beside, run_migrate, write
from tests.cli.config_migrate_machine_fakes import MACHINE, tracked
from tests.cli.config_migrate_running_fakes import ONE, run_watched, running_unit
from tests.factories import init_repo

UNTRACKED = OLD + MACHINE.split("\n", 1)[1]


def test_the_notice_comes_before_the_question_and_the_write_follows_a_yes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tracked(tmp_path)
    running_unit(tmp_path)

    code, terminal = run_watched(capsys, monkeypatch, path, answers=("y",))

    assert code == 0
    assert terminal.asked == 1
    assert ONE in terminal.err_when_asked[0]
    assert (tmp_path / "abk.local.yaml").exists()
    assert "project_limits" not in path.read_text()


def test_yes_prints_the_notice_and_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tracked(tmp_path)
    running_unit(tmp_path)

    code, terminal = run_migrate(capsys, monkeypatch, path, "--yes")

    assert code == 0
    assert ONE in terminal.err
    assert (tmp_path / "abk.local.yaml").exists()


def test_a_dry_run_prints_no_notice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tracked(tmp_path)
    running_unit(tmp_path)

    code, terminal = run_migrate(capsys, monkeypatch, path, "--dry-run")

    assert code == 0
    assert "is running" not in terminal.err


def test_a_run_with_nothing_to_do_prints_no_notice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tracked(tmp_path)
    running_unit(tmp_path)
    assert run_migrate(capsys, monkeypatch, path, "--yes")[0] == 0

    code, terminal = run_migrate(capsys, monkeypatch, path, "--yes")

    assert code == 0
    assert "nothing needed migrating" in terminal.out
    assert terminal.err.count("is running") == 1


def test_an_abk_yaml_outside_a_git_repository_runs_the_existing_steps_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write(tmp_path, UNTRACKED)
    running_unit(tmp_path)

    code, terminal = run_migrate(capsys, monkeypatch, path, "--yes")

    assert code == 0
    assert "is running" not in terminal.err
    assert "project_limits" in yaml.safe_load(path.read_text())
    assert "path: ../app" in path.read_text()
    assert beside(path) == ["runs", path.name + BACKUP_SUFFIX]


def test_an_abk_yaml_git_does_not_track_runs_the_existing_steps_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    init_repo(tmp_path)
    path = write(tmp_path, UNTRACKED)
    running_unit(tmp_path)

    code, terminal = run_migrate(capsys, monkeypatch, path, "--yes")

    assert code == 0
    assert "is running" not in terminal.err
    assert "path: ../app" in path.read_text()
    assert beside(path) == [".git", "runs", path.name + BACKUP_SUFFIX]
