"""`abk config --migrate` makes the test-kind rename in its one change, confirmation and write."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.runtimes.policy_apply import BACKUP_SUFFIX
from tests.cli.config_migrate_fakes import OLD, beside, run_migrate, write

WITH_TIER_KEYS = OLD + "  tier2_lock_wait_seconds: 600  # ten minutes\n"


def test_the_moves_and_the_rename_show_one_diff_ask_once_and_write_once_with_a_backup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write(tmp_path, WITH_TIER_KEYS)

    code, terminal = run_migrate(capsys, monkeypatch, path, answers=("y",))

    assert code == 0
    assert terminal.asked == 1
    assert len(terminal.shown) == 1
    assert "project_limits" in terminal.shown[0]
    assert "e2e_lock_wait_seconds: 600  # ten minutes" in terminal.shown[0]
    written = path.read_text()
    assert "global_limits:" in written
    assert "project_limits:" in written
    assert "e2e_lock_wait_seconds: 600  # ten minutes" in written
    assert "tier2_lock_wait_seconds" not in written
    assert beside(path) == [path.name + BACKUP_SUFFIX]
    assert path.with_name(path.name + BACKUP_SUFFIX).read_text() == WITH_TIER_KEYS


def test_a_file_needing_only_the_rename_is_migrated_and_then_needs_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    before = "version: 1\nglobal_limits:\n  tier2_lock_wait_seconds: 600\n"
    path = write(tmp_path, before)

    code, _ = run_migrate(capsys, monkeypatch, path, "--yes")
    migrated = path.read_text()
    again, terminal = run_migrate(capsys, monkeypatch, path)

    assert code == 0
    assert migrated == "version: 1\nglobal_limits:\n  e2e_lock_wait_seconds: 600\n"
    assert again == 0
    assert "nothing needed migrating" in terminal.out
    assert path.read_text() == migrated
    assert beside(path) == [path.name + BACKUP_SUFFIX]
