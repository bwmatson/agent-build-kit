"""The migration writes abk.yaml and abk.local.yaml both-or-neither, the local one first
(spec: config-migration, "Both files are written together, the local one first")."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

import pytest

from agent_build_kit.config_migrate import ConfigMigrateError
from agent_build_kit.config_migrate_write import write_both
from agent_build_kit.runtimes.policy_apply import BACKUP_SUFFIX
from tests.config_migrate_write_fakes import (
    BASE_NEW,
    BASE_OLD,
    LOCAL_NEW,
    LOCAL_OLD,
    fail_nth,
    files,
    merged,
    temporaries,
)


def unchanged(base: Path, overlay: Path, *, local: str | None = LOCAL_OLD) -> None:
    assert base.read_text() == BASE_OLD
    if local is None:
        assert not overlay.exists()
    else:
        assert overlay.read_text() == local


def test_a_write_replaces_both_files_and_backs_up_both_originals(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    base, overlay = files(tmp_path)
    base.chmod(0o640)
    overlay.chmod(0o600)

    write_both(base, BASE_NEW, LOCAL_NEW)

    assert base.read_text() == BASE_NEW
    assert overlay.read_text() == LOCAL_NEW
    base_backup = base.with_name("abk.yaml" + BACKUP_SUFFIX)
    local_backup = overlay.with_name("abk.local.yaml" + BACKUP_SUFFIX)
    assert base_backup.read_text() == BASE_OLD
    assert local_backup.read_text() == LOCAL_OLD
    assert base.stat().st_mode & 0o7777 == 0o640
    assert overlay.stat().st_mode & 0o7777 == 0o600
    assert temporaries(tmp_path) == []
    printed = capsys.readouterr().out
    assert str(base_backup) in printed
    assert str(local_backup) in printed


def test_a_created_local_file_has_no_backup(tmp_path: Path) -> None:
    base, overlay = files(tmp_path, local=None)

    write_both(base, BASE_NEW, LOCAL_NEW)

    assert overlay.read_text() == LOCAL_NEW
    assert base.with_name("abk.yaml" + BACKUP_SUFFIX).read_text() == BASE_OLD
    assert not overlay.with_name("abk.local.yaml" + BACKUP_SUFFIX).exists()
    assert temporaries(tmp_path) == []


def test_an_existing_backup_is_not_overwritten(tmp_path: Path) -> None:
    base, overlay = files(tmp_path)
    base.with_name("abk.yaml" + BACKUP_SUFFIX).write_text("first base\n")
    overlay.with_name("abk.local.yaml" + BACKUP_SUFFIX).write_text("first local\n")

    write_both(base, BASE_NEW, LOCAL_NEW)

    assert base.with_name("abk.yaml" + BACKUP_SUFFIX).read_text() == "first base\n"
    assert overlay.with_name("abk.local.yaml" + BACKUP_SUFFIX).read_text() == "first local\n"
    assert base.read_text() == BASE_NEW


def test_the_local_file_is_replaced_first_and_the_tracked_one_second(tmp_path: Path) -> None:
    base, overlay = files(tmp_path)
    replaced: list[Path] = []
    real = os.replace

    def spy(source: str | os.PathLike[str], target: str | os.PathLike[str]) -> None:
        replaced.append(Path(target))
        real(source, target)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(os, "replace", spy)
        write_both(base, BASE_NEW, LOCAL_NEW)

    assert [path.name for path in replaced if path in (base, overlay)] == [
        "abk.local.yaml",
        "abk.yaml",
    ]


def test_a_restored_local_file_keeps_its_own_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base, overlay = files(tmp_path)
    base.chmod(0o644)
    overlay.chmod(0o600)
    fail_nth(monkeypatch, "replace", 2, 2)

    with pytest.raises(ConfigMigrateError, match="abk.yaml"):
        write_both(base, BASE_NEW, LOCAL_NEW)

    assert overlay.read_text() == LOCAL_OLD
    assert overlay.stat().st_mode & 0o7777 == 0o600


@pytest.mark.parametrize("local", [LOCAL_OLD, None])
def test_a_failed_second_replacement_restores_the_local_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, local: str | None
) -> None:
    base, overlay = files(tmp_path, local=local)
    fail_nth(monkeypatch, "replace", 2, 2)

    with pytest.raises(ConfigMigrateError, match="abk.yaml"):
        write_both(base, BASE_NEW, LOCAL_NEW)

    unchanged(base, overlay, local=local)
    assert temporaries(tmp_path) == []


def test_a_failed_first_replacement_changes_neither_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base, overlay = files(tmp_path)
    fail_nth(monkeypatch, "replace", 1)

    with pytest.raises(ConfigMigrateError):
        write_both(base, BASE_NEW, LOCAL_NEW)

    unchanged(base, overlay)
    assert temporaries(tmp_path) == []


def test_a_temporary_file_that_reads_back_differently_changes_neither_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base, overlay = files(tmp_path)
    real_bytes, real_text = Path.read_bytes, Path.read_text

    def is_temporary(path: Path) -> bool:
        return (
            path.parent == tmp_path
            and path.name not in ("abk.yaml", "abk.local.yaml")
            and not path.name.endswith(BACKUP_SUFFIX)
        )

    def read_bytes(self: Path) -> bytes:
        if is_temporary(self):
            raise OSError(5, "Input/output error")
        return real_bytes(self)

    def read_text(self: Path, *args: Any, **kwargs: Any) -> str:
        if is_temporary(self):
            raise OSError(5, "Input/output error")
        return real_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_bytes", read_bytes)
    monkeypatch.setattr(Path, "read_text", read_text)

    with pytest.raises(ConfigMigrateError):
        write_both(base, BASE_NEW, LOCAL_NEW)

    monkeypatch.undo()
    unchanged(base, overlay)
    assert temporaries(tmp_path) == []


def test_a_failed_backup_changes_neither_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base, overlay = files(tmp_path)

    def refuse(source: object, target: object) -> None:
        raise OSError(13, "Permission denied")

    monkeypatch.setattr(shutil, "copy2", refuse)

    with pytest.raises(ConfigMigrateError):
        write_both(base, BASE_NEW, LOCAL_NEW)

    unchanged(base, overlay)
    assert temporaries(tmp_path) == []


@pytest.mark.parametrize("which", [1, 2], ids=["first-temporary", "second-temporary"])
def test_a_failed_write_of_either_temporary_file_changes_neither_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, which: int
) -> None:
    base, overlay = files(tmp_path)
    fail_nth(monkeypatch, "fdopen", which, which)

    with pytest.raises(ConfigMigrateError):
        write_both(base, BASE_NEW, LOCAL_NEW)

    unchanged(base, overlay)
    assert temporaries(tmp_path) == []


@pytest.mark.parametrize("restore", ["rename", "write"])
def test_a_run_whose_restore_fails_leaves_the_merged_configuration_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, restore: str
) -> None:
    base, overlay = files(tmp_path)
    before = merged(base, overlay)
    fail_nth(monkeypatch, "replace", 2)
    if restore == "write":
        fail_nth(monkeypatch, "fdopen", 3)

    with pytest.raises(ConfigMigrateError, match="abk.yaml"):
        write_both(base, BASE_NEW, LOCAL_NEW)

    monkeypatch.undo()
    assert base.read_text() == BASE_OLD
    assert overlay.read_text() == LOCAL_NEW
    assert merged(base, overlay) == before
    assert temporaries(tmp_path) == []


def test_an_existing_empty_local_file_keeps_its_mode(tmp_path: Path) -> None:
    base, overlay = files(tmp_path, local="")
    base.chmod(0o644)
    overlay.chmod(0o600)

    write_both(base, BASE_NEW, LOCAL_NEW)

    assert overlay.read_text() == LOCAL_NEW
    assert overlay.stat().st_mode & 0o7777 == 0o600


def test_a_failed_backup_of_the_local_file_names_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base, overlay = files(tmp_path)
    real = shutil.copy2

    def refuse_local(source: Path, target: Path, **kwargs: bool) -> object:
        if Path(source) == overlay:
            raise OSError(13, "Permission denied")
        return real(source, target, **kwargs)

    monkeypatch.setattr(shutil, "copy2", refuse_local)

    with pytest.raises(ConfigMigrateError, match="abk.local.yaml"):
        write_both(base, BASE_NEW, LOCAL_NEW)

    unchanged(base, overlay)
