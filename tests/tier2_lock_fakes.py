"""The tier 2 lock held by someone else, on a clock that moves only as the waiter sleeps.

The lock is a real `flock` on a real file, taken from another open file description as
another process would; the record in the file is the JSON line a holder writes."""

from __future__ import annotations

import fcntl
import json
import subprocess
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline import e2e, spans, wiring
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import Unit
from agent_build_kit.pipeline.wiring import build_runner
from tests.fake_clock import START, FakeClock, install

# How far each sleep of the waiting loop moves the clock on.
STEP = 10.0


class SleepingTime:
    """Stands in for the `time` module `stack_lock` reads: sleeping moves the clock on and
    then lets whoever was due to let go of the lock do so."""

    def __init__(self, clock: FakeClock) -> None:
        self.clock = clock
        self.began = clock.monotonic()
        self.due: list[tuple[float, Callable[[], None]]] = []

    def monotonic(self) -> float:
        return self.clock.monotonic()

    def elapsed(self) -> float:
        return self.clock.monotonic() - self.began

    def sleep(self, seconds: float) -> None:
        self.clock.advance(max(seconds, STEP))
        for entry in [d for d in self.due if d[0] <= self.elapsed()]:
            self.due.remove(entry)
            entry[1]()

    def release_at(self, seconds: float, action: Callable[[], None]) -> None:
        """Run `action` when the clock has moved `seconds` past where the test began."""
        self.due.append((seconds, action))


def install_clock(monkeypatch: pytest.MonkeyPatch, start: datetime = START) -> SleepingTime:
    sleeping = SleepingTime(install(monkeypatch, start))
    monkeypatch.setattr(e2e, "time", sleeping)
    return sleeping


def dead_pid() -> int:
    """A process id no process can have: past the largest the kernel hands out."""
    return int(Path("/proc/sys/kernel/pid_max").read_text()) + 1


def record_line(unit: str, pid: int, age: float = 0.0) -> str:
    """The line a holder writes: its unit, process and when it took the lock."""
    since = spans.clock.now() - timedelta(seconds=age)
    return json.dumps({"unit": unit, "pid": pid, "since": since.isoformat()}) + "\n"


class Foreign:
    """Another holder of the lock, with the record a holder leaves in the file."""

    def __init__(self, path: Path, unit: str = "other/1", pid: int | None = None, age: float = 0.0):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = path.open("a+")
        fcntl.flock(self.handle, fcntl.LOCK_EX)
        self.handle.seek(0)
        self.handle.truncate()
        self.handle.write(record_line(unit, dead_pid() if pid is None else pid, age))
        self.handle.flush()

    def release(self) -> None:
        if not self.handle.closed:
            fcntl.flock(self.handle, fcntl.LOCK_UN)
            self.handle.close()


@contextmanager
def held(path: Path) -> Iterator[Foreign]:
    """The lock taken by someone else for the length of the block."""
    other = Foreign(path)
    try:
        yield other
    finally:
        other.release()


class Ran:
    """The tests command, answered as a passing run; what the lock file said as it ran."""

    def __init__(self, lock: Path) -> None:
        self.lock = lock
        self.record_seen: str | None = None

    def __call__(self, command: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        if self.record_seen is None:
            self.record_seen = self.lock.read_text()
        return subprocess.CompletedProcess(command, 0, "1 passed in 0.01s\n", "")


def tier2_runner(
    workspace: Installation,
    store: UnitStore,
    monkeypatch: pytest.MonkeyPatch,
    log: list[str],
    unit: Unit,
) -> tuple[wiring.UnitRunner, Ran]:
    """The runner of `unit` whose tests command is `Ran`, over the workspace's tier 2 lock."""
    ran = Ran(workspace.state_dir / "tier2.lock")
    monkeypatch.setattr(wiring, "_run", ran)
    monkeypatch.setattr(wiring, "_head_sha", lambda cwd: "abc1234")
    built = build_runner(unit, store=store, installation=workspace, log=log.append)
    return built, ran
