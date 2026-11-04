"""The slots a whole-suite unit-test run takes, so no more than a set number run at once.

One lock file per slot in the planning repo's lock folder (`unit-test-slot-<n>.lock`). A run
takes the first free one without waiting; when all are taken it polls, often at first, until one
is free. The lock is an `flock`, which the kernel releases when the holder's process ends, so a
killed run cannot wedge a slot. The holder writes a `LockRecord` into its slot, as the e2e-test
lock does, so a status line and a waiting run can name it. A waiting run also holds a marker of
its own (`unit-test-waiting-<token>.lock`, locked and recorded the same way) for as long as it
waits, so `abk status` can name who waits; a marker whose process is gone is not locked and is
not listed. The wait is outside the unit-test command's time limit: the permit is taken before
that clock starts.

Waiting runs are served in a fixed order: by rank (a tuple of whole numbers, smaller is more urgent;
the caller computes it, and this module reads no unit), then by when the run began waiting, then by
the marker's token. A run takes a free slot only when no other live waiter comes before it in that
order, and a run that finds a slot free while a waiter exists makes a marker and goes through the
same rule, so it cannot take the slot of a waiter that has not polled yet. A run that finds a slot
free and no waiter takes it at once and makes no marker."""

from __future__ import annotations

import fcntl
import math
import os
import sys
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import IO

from agent_build_kit.pipeline import host, spans
from agent_build_kit.pipeline.e2e import LOCK_LOG_INTERVAL_SECONDS, LockRecord, read_lock_record
from agent_build_kit.pipeline.file_lock import POLL_SECONDS, Clock

_FIRST_POLL_SECONDS = 0.001
_WAITING_PREFIX = "unit-test-waiting-"
_WAITING_GLOB = f"{_WAITING_PREFIX}*.lock"

# A rank is the start key of a unit: smaller is more urgent, tuples compare element by element.
# `start_key(...)`'s `tuple[int, ...]` is passed as it is.
Rank = tuple[int, ...]

# Served after every rank a unit's start key can have (those begin with 0, 1 or 2).
LEAST_URGENT: Rank = (sys.maxsize,)


class WaiterRecord(LockRecord):
    """What a waiting run writes into its marker: the holder's record and the rank it waits at.
    A marker written without a rank (by an older kit) reads as `LEAST_URGENT`."""

    rank: Rank | None = None


# Where a waiter stands: its rank, when it began waiting (seconds since the epoch), and its
# marker's token, so any two waiters are ordered and the order is the same for every reader.
_Position = tuple[Rank, float, str]


@dataclass(frozen=True)
class _Waiter:
    token: str
    position: _Position
    record: WaiterRecord | None


def _position(record: WaiterRecord | None, token: str) -> _Position:
    """A waiter's place in the order; a marker that cannot be read goes last of its rank."""
    if record is None:
        return LEAST_URGENT, math.inf, token
    try:
        began = datetime.fromisoformat(record.since).timestamp()
    except ValueError:
        began = math.inf
    return (LEAST_URGENT if record.rank is None else record.rank), began, token


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


def _waiter_record(holder: str, rank: Rank) -> str:
    record = WaiterRecord(
        unit=holder,
        pid=os.getpid(),
        since=spans.clock.now().isoformat(),
        host=host.this_host(),
        rank=rank,
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
def _waiting(locks_dir: Path, holder: str, rank: Rank) -> Iterator[_Position]:
    """A marker that `holder` waits for a slot at `rank`, locked until the block ends; yields the
    marker's place in the order. The marker is written and locked under a name no reader looks
    for and then renamed, so a reader that sees it sees its record and its lock."""
    token = f"{os.getpid()}-{uuid.uuid4().hex[:8]}"
    path = locks_dir / f"{_WAITING_PREFIX}{token}.lock"
    staging = locks_dir / f"unit-test-registering-{token}.tmp"
    text = _waiter_record(holder, rank)
    try:
        with staging.open("a+") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            handle.write(text)
            handle.flush()
            staging.rename(path)
            try:
                yield _position(_read_waiter(text), token)
            finally:
                path.unlink(missing_ok=True)
                fcntl.flock(handle, fcntl.LOCK_UN)
    finally:
        staging.unlink(missing_ok=True)


def _read_waiter(text: str) -> WaiterRecord | None:
    try:
        return WaiterRecord.model_validate_json(text)
    except ValueError:
        return None


def _locked_text(path: Path) -> str | None:
    """The text of the file at `path` when its lock is held, None when it is not (or the file is
    gone). A shared, non-blocking `flock` on a separate open, released at once; the file is never
    created or changed."""
    try:
        handle = path.open("r")
    except FileNotFoundError:
        return None
    with handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError:
            return handle.read()
        fcntl.flock(handle, fcntl.LOCK_UN)
        return None


def _live_waiters(locks_dir: Path) -> list[_Waiter]:
    """The runs that wait now, in the order they will be served. A marker whose process is gone
    is not locked and is left out."""
    waiters: list[_Waiter] = []
    for path in locks_dir.glob(_WAITING_GLOB):
        text = _locked_text(path)
        if text is None:
            continue
        token = path.stem.removeprefix(_WAITING_PREFIX)
        record = _read_waiter(text)
        waiters.append(_Waiter(token, _position(record, token), record))
    return sorted(waiters, key=lambda waiter: waiter.position)


def _comes_first(locks_dir: Path, mine: _Position) -> bool:
    """Whether no other live waiter stands before the one at `mine`."""
    return all(
        waiter.position[2] == mine[2] or waiter.position > mine
        for waiter in _live_waiters(locks_dir)
    )


def _waiting_message(
    locks_dir: Path, paths: list[Path], limit: int, mine: _Position, waited: float
) -> str:
    """What a waiting run tells: who holds the slots, or, when a slot is free and the run waits
    only for a waiter ahead of it, which one."""
    said = f"waiting for a unit-test slot ({limit} at once)"
    if any(_locked_text(path) is None for path in paths):
        ahead = [waiter for waiter in _live_waiters(locks_dir) if waiter.position < mine]
        record = ahead[0].record if ahead else None
        behind = record.unit if record is not None and record.unit else "another waiting run"
        return f"{said}, behind {behind} which waits ahead, waited {int(waited)}s"
    return f"{said}, held by {_holders(paths)}, waited {int(waited)}s"


@contextmanager
def unit_test_slot(
    locks_dir: Path,
    limit: int | None,
    *,
    holder: str = "",
    rank: Rank = LEAST_URGENT,
    on_wait: Callable[[str], None] | None = None,
    clock: Clock | None = None,
) -> Iterator[float]:
    """Hold one of `limit` slots for the block, waiting for one when all are taken or when another
    live waiter stands before this run; yields the seconds waited. With no limit (`None`) nothing
    waits and no file is made. `rank` is the run's place in the order waiting runs are served
    (smaller first; the default is after every rank given). `on_wait` is told who holds the slots
    at the first miss and again each `LOCK_LOG_INTERVAL_SECONDS`. The holder's `LockRecord` is
    written into its slot and cleared on release, which happens however the block ends."""
    if limit is None:
        yield 0.0
        return
    clock = clock or time
    locks_dir.mkdir(parents=True, exist_ok=True)
    paths = [slot_path(locks_dir, index) for index in range(1, limit + 1)]
    handle = None if _live_waiters(locks_dir) else _take(paths)
    waited = 0.0
    if handle is None:
        with _waiting(locks_dir, holder, rank) as mine:
            began = clock.monotonic()
            pause = _FIRST_POLL_SECONDS
            next_say = 0.0
            polls = 0
            while True:
                handle = _take(paths) if _comes_first(locks_dir, mine) else None
                if handle is not None:
                    # A run that got a slot on its first poll never waited.
                    waited = clock.monotonic() - began if polls else 0.0
                    break
                polls += 1
                waited = clock.monotonic() - began
                if on_wait is not None and waited >= next_say:
                    on_wait(_waiting_message(locks_dir, paths, limit, mine, waited))
                    next_say = waited + LOCK_LOG_INTERVAL_SECONDS
                clock.sleep(pause)
                pause = min(pause * 2, POLL_SECONDS)
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
    """Whether the lock at `path` is held, and its record when it is."""
    text = _locked_text(path)
    return (False, None) if text is None else (True, read_lock_record(text))


def slot_status_lines(locks_dir: Path, limit: int | None) -> list[str]:
    """The `abk status` line for the slots: each one's holder and for how long, and the units
    that wait, in the order they will be served. None (an empty list) when no limit is set."""
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
    for waiter in _live_waiters(locks_dir):
        record = waiter.record
        name = record.unit if record is not None and record.unit else "an unnamed unit"
        waiting.append(f"{name} for {_age(record)}" if record is not None else name)
    if waiting:
        parts.append("waiting: " + ", ".join(waiting))
    return [f"unit-test slots ({limit} at once): " + "; ".join(parts)]
