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
from collections.abc import Iterator
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
