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

import fcntl
import os
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def file_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


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


def _replace_through_partial(path: Path, write: Callable[[Path], object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        write(partial)
        os.replace(partial, path)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise


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
