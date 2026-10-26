"""A clock that moves only when a test says so, standing in for `spans.clock`."""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime, timedelta

import pytest

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline import spans

START = datetime(2030, 1, 1, 9, 0, tzinfo=UTC)


class FakeClock:
    def __init__(self, start: datetime = START) -> None:
        self._start = start
        self._elapsed = 0.0
        self._lock = threading.Lock()

    def advance(self, seconds: float) -> None:
        with self._lock:
            self._elapsed += seconds

    def now(self) -> datetime:
        with self._lock:
            return self._start + timedelta(seconds=self._elapsed)

    def monotonic(self) -> float:
        with self._lock:
            return 1000.0 + self._elapsed


class Waits:
    """The sleeper: records each wait and moves the fake clock by it."""

    def __init__(self, clock: FakeClock) -> None:
        self.clock = clock
        self.slept: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.clock.advance(seconds)


def install(monkeypatch: pytest.MonkeyPatch, start: datetime = START) -> FakeClock:
    clock = FakeClock(start)
    monkeypatch.setattr(spans, "clock", clock)
    return clock


def span_lines(workspace: Installation) -> list[dict]:
    """The ledger's `span` lines, as written."""
    path = workspace.state_dir / "usage-ledger.jsonl"
    if not path.exists():
        return []
    lines = [json.loads(line) for line in path.read_text().splitlines() if line]
    return [line for line in lines if line.get("kind") == "span"]
