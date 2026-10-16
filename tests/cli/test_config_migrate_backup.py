"""`abk config --migrate` keeps one backup and writes through a temporary file."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from tests.cli.config_migrate_fakes import BACKUP_SUFFIX, OLD, beside, run_migrate, write


def test_the_first_write_copies_the_original_beside_the_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write(tmp_path)

    run_migrate(capsys, monkeypatch, path, "--yes")

    assert beside(path) == [path.name + BACKUP_SUFFIX]
    assert path.with_name(path.name + BACKUP_SUFFIX).read_text() == OLD


def test_a_later_migration_leaves_the_first_backup_as_it_was(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write(tmp_path)
    run_migrate(capsys, monkeypatch, path, "--yes")
    path.write_text(OLD.replace("7", "9"))

    code, _ = run_migrate(capsys, monkeypatch, path, "--yes")

    assert code == 0
    assert "project_limits:" in path.read_text()
    assert path.with_name(path.name + BACKUP_SUFFIX).read_text() == OLD


def test_the_write_keeps_the_mode_and_leaves_no_temporary_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write(tmp_path)
    path.chmod(0o640)

    run_migrate(capsys, monkeypatch, path, "--yes")

    assert path.stat().st_mode & 0o7777 == 0o640
    assert beside(path) == [path.name + BACKUP_SUFFIX]


def test_the_file_is_replaced_in_one_step_by_a_temporary_in_its_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write(tmp_path)
    replaced: list[tuple[Path, Path]] = []
    real = os.replace

    def spy(source: str | os.PathLike[str], target: str | os.PathLike[str]) -> None:
        replaced.append((Path(source), Path(target)))
        assert "project_limits" in Path(source).read_text()
        assert path.read_text() == OLD
        real(source, target)

    monkeypatch.setattr(os, "replace", spy)

    code, _ = run_migrate(capsys, monkeypatch, path, "--yes")

    assert code == 0
    assert len(replaced) == 1
    source, target = replaced[0]
    assert target == path
    assert source.parent == path.parent
    assert source != path
