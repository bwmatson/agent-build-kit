"""`abk config --migrate` leaves `emergency_extra` alone: no line added, moved or rewritten."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit import config
from agent_build_kit.config_migrate import migrate
from tests.cli.config_migrate_fakes import run_migrate, write

KEPT = "project_limits:\n  # the lane\n  emergency_extra: 2  # two\n"


def test_the_three_move_and_the_key_keeps_its_line_and_comment(tmp_path: Path) -> None:
    text = (
        "version: 1\n"
        "limits:\n"
        "  max_units_in_progress: 3\n"
        "  max_concurrent_stacks: 2\n"
        "  max_concurrent_restacks: 1\n" + KEPT
    )

    migrated = migrate(text)

    assert "  # the lane\n  emergency_extra: 2  # two\n" in migrated.text
    assert set(migrated.moved) == {
        "max_units_in_progress",
        "max_concurrent_stacks",
        "max_concurrent_restacks",
    }
    path = write(tmp_path, migrated.text)
    assert config.load(path).project_limits.emergency_extra == 2


def test_a_file_with_only_the_key_reports_nothing_needed_migrating(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    text = "version: 1\n" + KEPT
    path = write(tmp_path, text)

    code, terminal = run_migrate(capsys, monkeypatch, path, answers=None)

    assert code == 0
    assert "nothing needed migrating" in terminal.out
    assert path.read_text() == text
    assert config.load(path).project_limits.emergency_extra == 2


def test_a_migrated_file_without_the_key_does_not_gain_one(tmp_path: Path) -> None:
    path = write(tmp_path, migrate("version: 1\nlimits:\n  max_units_in_progress: 3\n").text)

    loaded = config.load(path)

    assert "emergency_extra" not in path.read_text()
    assert loaded.project_limits.max_units_in_progress == 3
    assert loaded.project_limits.emergency_extra == 1
