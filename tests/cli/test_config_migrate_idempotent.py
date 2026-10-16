"""`abk config --migrate` run again, or on a file with nothing to move, does nothing; a refusal
exits 2 and writes nothing."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.cli.config_migrate_fakes import BACKUP_SUFFIX, beside, run_migrate, write


def test_a_second_run_says_nothing_needed_migrating_and_makes_no_second_backup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write(tmp_path)
    run_migrate(capsys, monkeypatch, path, "--yes")
    migrated = path.read_text()
    path.with_name(path.name + BACKUP_SUFFIX).unlink()

    code, terminal = run_migrate(capsys, monkeypatch, path)

    assert code == 0
    assert terminal.asked == 0
    assert "nothing needed migrating" in terminal.out
    assert path.read_text() == migrated
    assert beside(path) == []


@pytest.mark.parametrize(
    "text", ["version: 1\n", "version: 1\nglobal_limits:\n  max_review_rounds: 3\n"]
)
def test_a_file_with_nothing_to_move_says_the_same(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], text: str
) -> None:
    path = write(tmp_path, text)

    code, terminal = run_migrate(capsys, monkeypatch, path, answers=None)

    assert code == 0
    assert "nothing needed migrating" in terminal.out
    assert path.read_text() == text
    assert beside(path) == []


def test_a_refusal_exits_2_and_writes_nothing_not_even_a_backup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    text = "version: 1\nlimits: {max_units_in_progress: 5}\n"
    path = write(tmp_path, text)

    code, terminal = run_migrate(capsys, monkeypatch, path, "--yes")

    assert code == 2
    assert "limits" in terminal.err
    assert "flow-style" in terminal.err
    assert path.read_text() == text
    assert beside(path) == []
