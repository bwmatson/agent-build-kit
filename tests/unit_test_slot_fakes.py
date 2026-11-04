"""Stand-ins for the waiters of the unit-test slots (spec: unit-test-concurrency): a waiting marker
held by the test, and a run that waits for a slot on a thread of its own and says when it has it."""

from __future__ import annotations

import fcntl
import json
import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from agent_build_kit.pipeline.unit_test_slots import unit_test_slot
from tests.waiting import wait_for


@contextmanager
def live_waiter(
    locks_dir: Path,
    token: str,
    unit: str,
    *,
    since: datetime,
    rank: tuple[int, ...] | None = None,
) -> Iterator[Path]:
    """A waiting marker as a run that waits makes it, locked for the block. `rank` None writes it
    as an older kit did, with no rank."""
    path = locks_dir / f"unit-test-waiting-{token}.lock"
    record: dict[str, object] = {
        "unit": unit,
        "pid": os.getpid(),
        "since": since.isoformat(),
        "host": "a-host",
    }
    if rank is not None:
        record["rank"] = list(rank)
    with path.open("a+") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        handle.write(json.dumps(record) + "\n")
        handle.flush()
        try:
            yield path
        finally:
            path.unlink(missing_ok=True)
            fcntl.flock(handle, fcntl.LOCK_UN)


def waiting_units(locks_dir: Path) -> list[str]:
    """The units named by the waiting markers in the folder, whoever holds them."""
    names: list[str] = []
    for path in sorted(locks_dir.glob("unit-test-waiting-*.lock")):
        try:
            names.append(json.loads(path.read_text())["unit"])
        except (OSError, ValueError, KeyError):
            continue
    return names


class WaitingRun:
    """A run on its own thread: it takes a slot, notes its unit in `order`, and keeps the slot
    until `release` is set."""

    def __init__(self) -> None:
        self.release = threading.Event()
        self.error: BaseException | None = None

    def until_waiting(self, locks_dir: Path, unit: str) -> None:
        """Return once `unit` has a waiting marker; raise what stopped the run instead."""
        wait_for(
            lambda: self.error is not None or unit in waiting_units(locks_dir),
            what=f"{unit} to wait",
        )
        if self.error is not None:
            raise self.error


@contextmanager
def waiting_run(
    locks_dir: Path,
    unit: str,
    *,
    rank: tuple[int, ...] | None,
    order: list[str],
    limit: int = 1,
) -> Iterator[WaitingRun]:
    """Start a run of `unit` (given no rank when `rank` is None) that waits for a slot; the block
    ends by releasing it and joining."""
    run = WaitingRun()

    def go() -> None:
        try:
            slot = (
                unit_test_slot(locks_dir, limit, holder=unit)  # given no rank
                if rank is None
                else unit_test_slot(locks_dir, limit, holder=unit, rank=rank)
            )
            with slot:
                order.append(unit)
                run.release.wait(timeout=20)
        except BaseException as error:  # noqa: BLE001 - handed to the test thread
            run.error = error

    thread = threading.Thread(target=go, daemon=True)
    thread.start()
    try:
        yield run
    finally:
        run.release.set()
        thread.join(timeout=20)
