"""`abk config --migrate` does not load the configuration, so it migrates a file that will not
load, and the migrated file loads cleanly."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from agent_build_kit.cli import main
from tests.cli.config_migrate_fakes import run_migrate, write

UNLOADABLE = "version: 1\nglobal_limits:\n  max_units_in_progress: 7\n  max_review_rounds: 3\n"


def test_a_file_whose_global_limits_hold_a_moved_setting_is_migrated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write(tmp_path, UNLOADABLE)
    assert main(["--config", str(path), "config"]) == 2
    capsys.readouterr()

    code, _ = run_migrate(capsys, monkeypatch, path, "--yes")

    assert code == 0
    assert yaml.safe_load(path.read_text())["project_limits"] == {"max_units_in_progress": 7}


def test_config_names_the_file_to_migrate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    named = write(tmp_path / "elsewhere", UNLOADABLE)
    other = write(tmp_path, UNLOADABLE)
    monkeypatch.chdir(tmp_path)

    code, _ = run_migrate(capsys, monkeypatch, named, "--yes")

    assert code == 0
    assert "project_limits:" in named.read_text()
    assert other.read_text() == UNLOADABLE


def test_the_migrated_file_loads_with_no_notice_and_abk_config_prints_both_blocks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write(tmp_path, UNLOADABLE)
    run_migrate(capsys, monkeypatch, path, "--yes")
    capsys.readouterr()

    code = main(["--config", str(path), "config"])

    captured = capsys.readouterr()
    assert code == 0
    assert captured.err == ""
    shown = yaml.safe_load(captured.out)
    assert shown["project_limits"]["max_units_in_progress"] == 7
    assert shown["global_limits"]["max_review_rounds"] == 3
