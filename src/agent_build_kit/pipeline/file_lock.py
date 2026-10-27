"""A blocking, exclusive lock on a file, for work that must not interleave.

Units build in parallel — threads within a tick, and ticks that overlap — and
a few things they share cannot take two writers at once: the unit store, whose
every change is a read-modify-write of one JSON file, and a repo's `.git`,
where two `git worktree add` or `git push` calls at the same moment fail on
git's own lock files instead of waiting their turn.

`flock` on a file of its own covers both kinds of concurrency: each `open` is a
separate lock holder, so two threads contend exactly as two processes do, and
the kernel releases it if the holder dies. Unlike `workspaces.branch_lock`,
which refuses when busy because the holder may be building for an hour, this
waits: whatever holds it is done in seconds.
"""

from __future__ import annotations

import errno
import fcntl
import os
import re
import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import AbstractContextManager, contextmanager
from pathlib import Path
from typing import IO, TYPE_CHECKING, Protocol

from agent_build_kit.pipeline import host
from agent_build_kit.settings import settings

if TYPE_CHECKING:

    class Located(Protocol):
        """Where locks are kept: an `Installation` is one."""

        @property
        def local_dir(self) -> Path: ...


POLL_SECONDS = 0.05
_FIRST_POLL_SECONDS = 0.001
_RENAME_RETRIES = 5
_RENAME_FIRST_DELAY = 0.1


class Clock(Protocol):
    """What the wait reads: the time and a way to let it pass."""

    def monotonic(self) -> float: ...

    def sleep(self, seconds: float, /) -> None: ...


class LockTimeout(TimeoutError):
    """A lock stayed held for the whole wait."""


def wait_for_flock(
    handle: IO[str],
    timeout: float | None,
    on_busy: Callable[[float], None] | None = None,
    clock: Clock | None = None,
) -> None:
    """Take the exclusive `flock` on `handle`, polling for up to `timeout` seconds (None waits
    for ever), often at first so a lock held for a moment is not waited on for a whole
    interval. `on_busy` is told how long has been waited at each miss; `TimeoutError` is
    raised when the deadline passes, for the caller to word. `clock` is anything with
    `monotonic` and `sleep` (the `time` module when None)."""
    clock = clock or time
    began = clock.monotonic()
    pause = _FIRST_POLL_SECONDS
    while True:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        except BlockingIOError:
            now = clock.monotonic()
            if timeout is not None and now - began >= timeout:
                raise TimeoutError from None
            if on_busy is not None:
                on_busy(now - began)
            clock.sleep(pause)
            pause = min(pause * 2, POLL_SECONDS)


@contextmanager
def file_lock(path: Path, timeout: float | None = None) -> Iterator[None]:
    """Hold the lock on `path`, polling for up to `timeout` seconds (the `lock_wait_seconds`
    setting when None) and raising `LockTimeout` when it stays held."""
    wait = settings.lock_wait_seconds if timeout is None else timeout
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        try:
            wait_for_flock(handle, wait)
        except TimeoutError:
            raise LockTimeout(
                f"{path} stayed locked for {wait:g}s; another process holds it "
                f"(ABK_LOCK_WAIT_SECONDS sets the wait)"
            ) from None
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def change_lock(inst: Located, change: str, name: str) -> AbstractContextManager[None]:
    """The lock on one of a change's files, kept at `<local dir>/locks/changes/<change>/<name>.lock`
    outside the repository.

    The local directory is `planning.local_dir` when set, else `<planning home>/local`, else the
    state directory of a separate planning repo.
    """
    return file_lock(change_lock_path(inst.local_dir, change, name))


def change_lock_path(local_dir: Path, change: str, name: str) -> Path:
    """Where the lock `name` on `change` is kept under `local_dir`."""
    return local_dir / "locks" / "changes" / change / f"{name}.lock"


@contextmanager
def try_file_lock(path: Path) -> Iterator[bool]:
    """Take the lock if it is free, without waiting: yields whether it was taken."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def atomic_write_text(path: Path, text: str) -> None:
    """Write `text` over `path` so a reader sees the old file or the new, never half.

    Written aside under a name of this process's own, so two writers do not share it, and
    renamed into place last; whatever is raised, the temporary is removed and the old file stays.
    Writers on two threads of one process share the name, so they hold the file lock around it.
    """
    _replace_through_partial(path, lambda partial: partial.write_text(text))


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """`atomic_write_text` for bytes."""
    _replace_through_partial(path, lambda partial: partial.write_bytes(data))


def _rename_refused(error: OSError) -> bool:
    return isinstance(error, PermissionError) or error.errno == errno.EBUSY


def _replace_through_partial(path: Path, write: Callable[[Path], object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    name = re.sub(r"[^A-Za-z0-9._-]", "_", host.this_host())
    partial = path.with_name(f"{path.name}.{name}.{os.getpid()}.tmp")
    try:
        write(partial)
        _sync(partial)
        delay = _RENAME_FIRST_DELAY
        for attempt in range(_RENAME_RETRIES + 1):
            try:
                os.replace(partial, path)
                break
            except OSError as error:
                if not _rename_refused(error) or attempt == _RENAME_RETRIES:
                    raise
                time.sleep(delay)
                delay *= 2
        _sync_directory(path.parent)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise


def _sync(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _sync_directory(directory: Path) -> None:
    """Several remote filesystems refuse a directory fsync; the file itself is already synced."""
    try:
        _sync(directory)
    except OSError:
        pass


def with_missing_lines(text: str, lines: Sequence[str]) -> str:
    """`text` with the `lines` it lacks added, each once.

    Lines are compared stripped; a newline separates them from the text already there only
    when it does not end in one. `text` itself when nothing is missing.
    """
    present = {line.strip() for line in text.splitlines()}
    missing = [line for line in dict.fromkeys(lines) if line.strip() not in present]
    if not missing:
        return text
    separator = "" if not text or text.endswith("\n") else "\n"
    added = "\n".join(missing)
    return f"{text}{separator}{added}\n"


def append_missing_lines(path: Path, lines: Sequence[str]) -> bool:
    """Add the `lines` a text file lacks (see `with_missing_lines`), creating the file when it
    is missing. Returns whether the file was written."""
    text = path.read_text() if path.exists() else ""
    added = with_missing_lines(text, lines)
    if added == text:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, added)
    return True
