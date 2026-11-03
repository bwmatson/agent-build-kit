"""The slots a whole-suite unit-test run takes, so no more than a set number run at once.

One lock file per slot in the planning repo's lock folder (`unit-test-slot-<n>.lock`). A run
takes the first free one without waiting; when all are taken it polls, often at first, until one
is free. The lock is an `flock`, which the kernel releases when the holder's process ends, so a
killed run cannot wedge a slot. The holder writes a `LockRecord` into its slot, as the e2e-test
lock does, so a status line and a waiting run can name it. A waiting run also holds a marker of
its own (`unit-test-waiting-<token>.lock`, locked and recorded the same way) for as long as it
waits, so `abk status` can name who waits; a marker whose process is gone is not locked and is
not listed. The wait is outside the unit-test command's time limit: the permit is taken before
that clock starts."""

from __future__ import annotations

import fcntl
import os
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import IO

from agent_build_kit.pipeline import host, spans
from agent_build_kit.pipeline.e2e import LOCK_LOG_INTERVAL_SECONDS, LockRecord, read_lock_record
from agent_build_kit.pipeline.file_lock import POLL_SECONDS, Clock

_FIRST_POLL_SECONDS = 0.001
_WAITING_GLOB = "unit-test-waiting-*.lock"


def slot_path(locks_dir: Path, index: int) -> Path:
    """The lock file of slot `index` (from 1)."""
    return locks_dir / f"unit-test-slot-{index}.lock"


def _record(holder: str) -> str:
    record = LockRecord(
        unit=holder,
        pid=os.getpid(),
        since=spans.clock.now().isoformat(),
        host=host.this_host(),
    )
    return record.model_dump_json() + "\n"


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
def _waiting(locks_dir: Path, holder: str) -> Iterator[None]:
    """A marker that `holder` waits for a slot, locked until the block ends."""
    path = locks_dir / f"unit-test-waiting-{os.getpid()}-{uuid.uuid4().hex[:8]}.lock"
    with path.open("a+") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        handle.write(_record(holder))
        handle.flush()
        try:
            yield
        finally:
            path.unlink(missing_ok=True)
            fcntl.flock(handle, fcntl.LOCK_UN)


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
    handle = _take(paths)
    waited = 0.0
    if handle is None:
        with _waiting(locks_dir, holder):
            began = clock.monotonic()
            pause = _FIRST_POLL_SECONDS
            next_say = 0.0
            while handle is None:
                waited = clock.monotonic() - began
                if on_wait is not None and waited >= next_say:
                    on_wait(
                        f"waiting for a unit-test slot ({limit} at once), held by "
                        f"{_holders(paths)}, waited {int(waited)}s"
                    )
                    next_say = waited + LOCK_LOG_INTERVAL_SECONDS
                clock.sleep(pause)
                pause = min(pause * 2, POLL_SECONDS)
                handle = _take(paths)
            waited = clock.monotonic() - began
    try:
        handle.truncate(0)
        handle.write(_record(holder))
        handle.flush()
        yield waited
    finally:
        handle.truncate(0)
        fcntl.flock(handle, fcntl.LOCK_UN)
        handle.close()


def _age(record: LockRecord) -> str:
    try:
        seconds = (spans.clock.now() - datetime.fromisoformat(record.since)).total_seconds()
    except ValueError:
        return "?"
    minutes, rest = divmod(int(max(seconds, 0)), 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes}m {rest}s" if hours else f"{minutes}m {rest}s"


def _probe(path: Path) -> tuple[bool, LockRecord | None]:
    """Whether the lock at `path` is held, and its record when it is. A shared, non-blocking
    `flock` on a separate open, released at once; the file is never created or changed."""
    try:
        handle = path.open("r")
    except FileNotFoundError:
        return False, None
    with handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError:
            return True, read_lock_record(handle.read())
        fcntl.flock(handle, fcntl.LOCK_UN)
        return False, None


def slot_status_lines(locks_dir: Path, limit: int | None) -> list[str]:
    """The `abk status` line for the slots: each one's holder and for how long, and the units
    that wait. None (an empty list) when no limit is set."""
    if limit is None:
        return []
    parts: list[str] = []
    for index in range(1, limit + 1):
        held, record = _probe(slot_path(locks_dir, index))
        if not held:
            parts.append(f"slot {index} free")
        elif record is None or not record.unit:
            parts.append(f"slot {index} held by an unnamed holder")
        else:
            parts.append(f"slot {index} held by {record.unit} for {_age(record)}")
    waiting = []
    for path in sorted(locks_dir.glob(_WAITING_GLOB)):
        held, record = _probe(path)
        if held:
            name = record.unit if record is not None and record.unit else "an unnamed unit"
            waiting.append(f"{name} for {_age(record)}" if record is not None else name)
    if waiting:
        parts.append("waiting: " + ", ".join(waiting))
    return [f"unit-test slots ({limit} at once): " + "; ".join(parts)]
