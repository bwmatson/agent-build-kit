"""Atomic writes name the host and pid, sync before the rename and retry a busy rename."""

from __future__ import annotations

import errno
import os
import stat
import time
from pathlib import Path

import pytest

from agent_build_kit.pipeline import host
from agent_build_kit.pipeline.file_lock import atomic_write_text


@pytest.fixture(autouse=True)
def no_sleeping(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(time, "sleep", lambda seconds: None)


def record_calls(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    """The fsyncs (of a file or a directory) and replaces, in the order they happen."""
    calls: list[tuple[str, str]] = []
    real_fsync, real_replace = os.fsync, os.replace

    def fsync(fd: int) -> None:
        kind = "dir" if stat.S_ISDIR(os.fstat(fd).st_mode) else "file"
        calls.append(("fsync", kind))
        real_fsync(fd)

    def replace(source: Path, target: Path) -> None:
        calls.append(("replace", Path(source).name))
        real_replace(source, target)

    monkeypatch.setattr(os, "fsync", fsync)
    monkeypatch.setattr(os, "replace", replace)
    return calls


def test_the_temporary_is_named_for_the_host_and_pid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(host, "this_host", lambda: "my box:1/x")
    calls = record_calls(monkeypatch)

    atomic_write_text(tmp_path / "units.json", "x")

    assert ("replace", f"units.json.my_box_1_x.{os.getpid()}.tmp") in calls


def test_the_file_is_synced_before_the_rename_and_the_directory_after(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(host, "this_host", lambda: "box")
    calls = record_calls(monkeypatch)

    atomic_write_text(tmp_path / "a.json", "x")

    order = [call[0] if call[0] == "replace" else f"fsync-{call[1]}" for call in calls]
    assert order == ["fsync-file", "replace", "fsync-dir"]


def test_a_directory_fsync_that_fails_is_ignored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(host, "this_host", lambda: "box")
    real = os.fsync
    refused: list[int] = []

    def fsync(fd: int) -> None:
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            refused.append(fd)
            raise OSError(errno.EINVAL, "no")
        real(fd)

    monkeypatch.setattr(os, "fsync", fsync)

    atomic_write_text(tmp_path / "a.json", "x")

    assert refused
    assert (tmp_path / "a.json").read_text() == "x"
    assert [p.name for p in tmp_path.iterdir()] == ["a.json"]


def test_a_rename_refused_twice_is_retried(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(host, "this_host", lambda: "box")
    real, refused = os.replace, []

    def replace(source: Path, target: Path) -> None:
        if len(refused) < 2:
            refused.append(1)
            raise PermissionError(errno.EACCES, "open elsewhere")
        real(source, target)

    monkeypatch.setattr(os, "replace", replace)

    atomic_write_text(tmp_path / "a.json", "new")

    assert (tmp_path / "a.json").read_text() == "new"
    assert len(refused) == 2


def test_a_rename_that_stays_busy_raises_after_five_retries_and_keeps_the_old_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(host, "this_host", lambda: "box")
    target = tmp_path / "a.json"
    target.write_text("old")
    attempts: list[int] = []

    def replace(source: Path, target: Path) -> None:
        attempts.append(1)
        raise OSError(errno.EBUSY, "busy")

    monkeypatch.setattr(os, "replace", replace)

    with pytest.raises(OSError) as raised:
        atomic_write_text(target, "new")

    assert raised.value.errno == errno.EBUSY
    assert len(attempts) == 6
    assert target.read_text() == "old"
    assert [p.name for p in tmp_path.iterdir()] == ["a.json"]


def test_a_failed_write_leaves_no_temporary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(host, "this_host", lambda: "box")

    def fsync(fd: int) -> None:
        raise OSError(errno.EIO, "disk")

    monkeypatch.setattr(os, "fsync", fsync)

    with pytest.raises(OSError):
        atomic_write_text(tmp_path / "a.json", "x")

    assert list(tmp_path.iterdir()) == []
