"""Whether locks taken in a directory exclude a second process.

The state's read-modify-write files are guarded by `flock` files beside them, and a filesystem
that accepts a lock and excludes nothing makes every update racy without a sign. The probe holds
a lock in the directory and asks a second interpreter, a separate process with its own handle,
for the same one.
"""

from __future__ import annotations

import errno
import fcntl
import json
import os
import subprocess
import sys
import time
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path

from agent_build_kit.model import Frozen
from agent_build_kit.pipeline import host, mounts
from agent_build_kit.pipeline.file_lock import atomic_write_text
from agent_build_kit.pipeline.mounts import Mount

CACHE_NAME = "state-lock-probe.json"

# Seconds the second process has to answer, and how long a pass is trusted.
CHILD_TIMEOUT = 10.0
CACHE_SECONDS = 24 * 3600.0

# What the second process runs: take the lock at once or not at all, and say which.
_CHILD = """
import errno, fcntl, sys
with open(sys.argv[1], "a") as handle:
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        print("granted")
    except BlockingIOError:
        print("blocked")
    except OSError as error:
        print("error:%d" % (error.errno or 0))
"""

_SMB_FIX = "mount the share with `nobrl`, or put planning.state_dir on a local disk"
_NFS_FIX = (
    "mount with lock support (lockd and statd running, no `nolock`) or `local_lock=all`, "
    "or put planning.state_dir on a local disk"
)
_FIXES = {"cifs": _SMB_FIX, "smb3": _SMB_FIX, "nfs": _NFS_FIX, "nfs4": _NFS_FIX}
_NO_LOCKS = (
    "this filesystem does not provide locks: use a network filesystem that does, or keep "
    "planning.state_dir on a local disk and sync it another way"
)


class ProbeResult(Frozen):
    passed: bool
    detail: str
    fix: str = ""


def _ask(path: Path, spawn: Callable[..., subprocess.CompletedProcess[str]]) -> str:
    argv = [sys.executable, "-I", "-c", _CHILD, str(path)]
    return spawn(argv, capture_output=True, text=True, timeout=CHILD_TIMEOUT).stdout.strip()


def _failed(mount: Mount, why: str) -> ProbeResult:
    fix = _FIXES.get(mount.fstype, _NO_LOCKS)
    return ProbeResult(
        passed=False, detail=f"locks in {mount.fstype} state do not work: {why}", fix=fix
    )


def probe_locking(
    directory: Path,
    spawn: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    mount: Mount | None = None,
) -> ProbeResult:
    """Hold a lock in `directory` and ask a second process for it; `mount` is looked up when
    not given."""
    mount = mount or mounts.mount_of(directory)
    path = directory / f".abk-lock-probe-{host.this_host()}-{os.getpid()}"
    try:
        try:
            directory.mkdir(parents=True, exist_ok=True)
            handle = path.open("a")
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                handle.close()
                raise
        except OSError as error:
            number = error.errno or 0
            name = errno.errorcode.get(number, "unknown")
            return _failed(mount, f"this process could not take the lock: error {number} ({name})")
        with handle:
            try:
                answer = _ask(path, spawn)
            except subprocess.TimeoutExpired:
                return _failed(mount, f"the second process timed out after {CHILD_TIMEOUT:g} s")
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)
        if answer == "granted":
            return _failed(mount, "two processes both held the lock")
        if answer.startswith("error:"):
            number = int(answer.partition(":")[2] or 0)
            name = errno.errorcode.get(number, "unknown")
            return _failed(mount, f"the second process got error {number} ({name})")
        if answer != "blocked":
            return _failed(mount, f"the second process answered {answer!r}")
        try:
            freed = _ask(path, spawn)
        except subprocess.TimeoutExpired:
            return _failed(mount, f"the second process timed out after {CHILD_TIMEOUT:g} s")
        if freed != "granted":
            return _failed(mount, "the lock was still held after it was released")
        return ProbeResult(passed=True, detail=f"locks exclude a second process on {mount.fstype}")
    finally:
        with suppress(OSError):
            path.unlink()


def _key(mount: Mount) -> dict[str, str]:
    return {"source": mount.source, "fstype": mount.fstype, "options": mount.options}


def cached_probe(
    local_dir: Path, directory: Path, mount: Mount, *, now: Callable[[], float] | None = None
) -> ProbeResult:
    """A pass cached in `local_dir` for the same mount within a day, else a fresh probe; `now`
    defaults to `time.time`, read from this module's `time`."""
    clock = now or time.time
    cache = local_dir / CACHE_NAME
    with suppress(OSError, ValueError, TypeError, KeyError):
        saved = json.loads(cache.read_text(encoding="utf-8"))
        if saved["mount"] == _key(mount) and 0 <= clock() - saved["time"] < CACHE_SECONDS:
            return ProbeResult(passed=True, detail="cached pass")
    result = probe_locking(directory, mount=mount)
    if result.passed:
        local_dir.mkdir(parents=True, exist_ok=True)
        atomic_write_text(cache, json.dumps({"mount": _key(mount), "time": clock()}))
    return result
