"""The lock probe: a second process is refused while the first holds the lock (spec:
state-locking-on-a-share)."""

from __future__ import annotations

import errno
import fcntl
import json
import os
import subprocess
from pathlib import Path

import pytest

from agent_build_kit.pipeline import lock_probe
from agent_build_kit.pipeline.lock_probe import CACHE_NAME, cached_probe, probe_locking
from agent_build_kit.pipeline.mounts import Mount
from tests.lock_probe_fakes import count_probes, mount

HOUR = 3600.0


def answering(text: str):
    """A `spawn` whose child printed `text`."""

    def spawn(argv, **kwargs):
        return subprocess.CompletedProcess(argv, 0, stdout=text + "\n", stderr="")

    return spawn


def test_a_working_directory_passes_with_a_real_child_and_leaves_no_probe_file(
    tmp_path: Path,
) -> None:
    result = probe_locking(tmp_path)

    assert result.passed, result.detail
    assert list(tmp_path.iterdir()) == []


def test_a_granted_lock_fails_saying_two_processes_held_it(tmp_path: Path) -> None:
    result = probe_locking(tmp_path, answering("granted"), mount("cifs"))

    assert not result.passed
    assert "two processes" in result.detail
    assert "cifs" in result.detail
    assert list(tmp_path.iterdir()) == []


def test_an_errno_fails_naming_it_and_the_mount_type(tmp_path: Path) -> None:
    result = probe_locking(tmp_path, answering(f"error:{errno.ENOLCK}"), mount("nfs4"))

    assert not result.passed
    assert str(errno.ENOLCK) in result.detail or "ENOLCK" in result.detail
    assert "nfs4" in result.detail
    assert list(tmp_path.iterdir()) == []


def test_a_silent_child_times_out_and_the_first_lock_is_released(tmp_path: Path) -> None:
    directory = tmp_path / "probed"
    directory.mkdir()
    kept = tmp_path / "kept"
    held_while_asking: list[bool] = []

    def silent(argv, **kwargs):
        [probe_file] = directory.iterdir()
        os.link(probe_file, kept)
        with kept.open("a") as handle:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                held_while_asking.append(False)
            except BlockingIOError:
                held_while_asking.append(True)
        raise subprocess.TimeoutExpired(argv, kwargs.get("timeout", 10))

    result = probe_locking(directory, silent, mount())

    assert held_while_asking == [True]
    assert not result.passed
    assert "timed out" in result.detail
    with kept.open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    assert list(directory.iterdir()) == []


@pytest.mark.parametrize(
    ("fstype", "word"),
    [("cifs", "nobrl"), ("nfs4", "local_lock=all"), ("9p", "local disk"), ("drvfs", "local disk")],
)
def test_the_fix_names_what_suits_the_mount(tmp_path: Path, fstype: str, word: str) -> None:
    result = probe_locking(tmp_path, answering("granted"), mount(fstype))

    assert word in result.fix


def test_a_pass_is_cached_in_the_local_directory_for_the_same_mount(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    probed = count_probes(monkeypatch).directories
    local, state = tmp_path / "local", tmp_path / "state"
    local.mkdir()

    cached_probe(local, state, mount("nfs4"), now=lambda: 1000.0)
    again = cached_probe(local, state, mount("nfs4"), now=lambda: 1000.0 + HOUR)

    assert again.passed
    assert len(probed) == 1
    assert json.loads((local / CACHE_NAME).read_text())


def test_a_pass_older_than_a_day_is_probed_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    probed = count_probes(monkeypatch).directories
    local = tmp_path / "local"
    local.mkdir()

    cached_probe(local, tmp_path, mount("nfs4"), now=lambda: 1000.0)
    cached_probe(local, tmp_path, mount("nfs4"), now=lambda: 1000.0 + 25 * HOUR)

    assert len(probed) == 2


@pytest.mark.parametrize(
    "changed",
    [
        mount("nfs4", source="other"),
        mount("cifs"),
        mount("nfs4", options="rw,nolock"),
    ],
)
def test_a_pass_is_not_reused_for_another_source_type_or_options(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, changed: Mount
) -> None:
    probed = count_probes(monkeypatch).directories
    local = tmp_path / "local"
    local.mkdir()

    cached_probe(local, tmp_path, mount("nfs4"), now=lambda: 1000.0)
    cached_probe(local, tmp_path, changed, now=lambda: 1000.0 + HOUR)

    assert len(probed) == 2


def test_a_lock_this_process_cannot_take_fails_with_the_mount_fix_and_leaves_no_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(handle, operation):
        raise OSError(errno.ENOLCK, "No locks available")

    monkeypatch.setattr(lock_probe.fcntl, "flock", refuse)

    result = probe_locking(tmp_path, answering("blocked"), mount("nfs4"))

    assert not result.passed
    assert "ENOLCK" in result.detail
    assert "nfs4" in result.detail
    assert "local_lock=all" in result.fix
    assert list(tmp_path.iterdir()) == []
