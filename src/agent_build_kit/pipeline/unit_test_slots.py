"""The slots a whole-suite unit-test run takes, so no more than a set number run at once.

One lock file per slot in the planning repo's lock folder (`unit-test-slot-<n>.lock`). A run
takes the first free one without waiting; when all are taken it polls, often at first, until one
is free. The lock is an `flock`, which the kernel releases when the holder's process ends, so a
killed run cannot wedge a slot. The holder writes a `LockRecord` into its slot, as the e2e-test
lock does, so a status line and a waiting run can name it. The wait is outside the unit-test
command's time limit: the permit is taken before that clock starts."""

from __future__ import annotations

import fcntl
import os
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import IO

from agent_build_kit.pipeline import host, spans
from agent_build_kit.pipeline.e2e import LOCK_LOG_INTERVAL_SECONDS, LockRecord, read_lock_record
from agent_build_kit.pipeline.file_lock import POLL_SECONDS, Clock

_FIRST_POLL_SECONDS = 0.001


def slot_path(locks_dir: Path, index: int) -> Path:
    """The lock file of slot `index` (from 1)."""
    return locks_dir / f"unit-test-slot-{index}.lock"


def _take(paths: list[Path]) -> IO[str] | None:
    """The open handle of the first slot that is free, locked; None when all are taken."""
    for path in paths:
        handle = path.open("a+")
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            handle.close()
            continue
        return handle
    return None


def _holders(paths: list[Path]) -> str:
    """Who holds the slots, as the waiting message names them."""
    named: list[str] = []
    for path in paths:
        try:
            record = read_lock_record(path.read_text())
        except OSError:
            record = None
        named.append(record.unit if record is not None and record.unit else "an unnamed holder")
    return ", ".join(named)


@contextmanager
def unit_test_slot(
    locks_dir: Path,
    limit: int | None,
    *,
    holder: str = "",
    on_wait: Callable[[str], None] | None = None,
    clock: Clock | None = None,
) -> Iterator[float]:
    """Hold one of `limit` slots for the block, waiting for one when all are taken; yields the
    seconds waited. With no limit (`None`) nothing waits and no file is made. `on_wait` is told
    who holds the slots at the first miss and again each `LOCK_LOG_INTERVAL_SECONDS`. The
    holder's `LockRecord` is written into its slot and cleared on release, which happens however
    the block ends."""
    if limit is None:
        yield 0.0
        return
    clock = clock or time
    locks_dir.mkdir(parents=True, exist_ok=True)
    paths = [slot_path(locks_dir, index) for index in range(1, limit + 1)]
    began = clock.monotonic()
    pause = _FIRST_POLL_SECONDS
    next_say = 0.0
    handle = _take(paths)
    waited = 0.0
    while handle is None:
        waited = clock.monotonic() - began
        if on_wait is not None and waited >= next_say:
            on_wait(
                f"waiting for a unit-test slot ({limit} at once), held by {_holders(paths)}, "
                f"waited {int(waited)}s"
            )
            next_say = waited + LOCK_LOG_INTERVAL_SECONDS
        clock.sleep(pause)
        pause = min(pause * 2, POLL_SECONDS)
        handle = _take(paths)
        if handle is not None:
            waited = clock.monotonic() - began
    try:
        handle.truncate(0)
        record = LockRecord(
            unit=holder,
            pid=os.getpid(),
            since=spans.clock.now().isoformat(),
            host=host.this_host(),
        )
        handle.write(record.model_dump_json() + "\n")
        handle.flush()
        yield waited
    finally:
        handle.truncate(0)
        fcntl.flock(handle, fcntl.LOCK_UN)
        handle.close()
