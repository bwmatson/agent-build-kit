"""`abk config --migrate` makes the `max_unit_lines` move in the same one change, confirmation
and write as the limits move."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from agent_build_kit.runtimes.policy_apply import BACKUP_SUFFIX
from tests.cli.config_migrate_fakes import OLD, beside, run_migrate, write

WITH_CEILING = OLD + "  # the biggest unit\n  max_unit_lines: 900  # nine hundred\n"


def test_both_moves_show_one_diff_ask_once_and_write_once_with_a_backup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write(tmp_path, WITH_CEILING)

    code, terminal = run_migrate(capsys, monkeypatch, path, answers=("y",))

    assert code == 0
    assert terminal.asked == 1
    assert len(terminal.shown) == 1
    assert "project_limits" in terminal.shown[0]
    assert "full: 900  # nine hundred" in terminal.shown[0]
    written = path.read_text()
    loaded = yaml.safe_load(written)
    assert loaded["review"] == {"ceilings": {"full": 900}}
    assert loaded["project_limits"]["max_units_in_progress"] == 7
    assert "max_unit_lines" not in written
    assert beside(path) == [path.name + BACKUP_SUFFIX]
    assert path.with_name(path.name + BACKUP_SUFFIX).read_text() == WITH_CEILING


def test_a_file_needing_only_this_move_is_migrated_and_then_needs_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write(tmp_path, "version: 1\nglobal_limits:\n  max_unit_lines: 900\n")

    code, _ = run_migrate(capsys, monkeypatch, path, "--yes")
    migrated = path.read_text()
    again, terminal = run_migrate(capsys, monkeypatch, path)

    assert code == 0
    assert yaml.safe_load(migrated)["review"] == {"ceilings": {"full": 900}}
    assert again == 0
    assert "nothing needed migrating" in terminal.out
    assert path.read_text() == migrated


def test_a_refused_move_writes_nothing_and_leaves_no_backup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    before = WITH_CEILING + "review:\n  ceilings:\n    full: 800\n"
    path = write(tmp_path, before)

    code, terminal = run_migrate(capsys, monkeypatch, path, "--yes")

    assert code != 0
    assert "max_unit_lines" in terminal.err
    assert path.read_text() == before
    assert beside(path) == []
