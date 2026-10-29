"""The stand-in agent that hangs after its stdio goes writes what it has to say first.

The run kills such an agent a grace after its stdout closes, so a line written after
the close is a line a loaded machine may not have written yet. The order is observed
here without a clock: what the agent does, in the order it does it.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

import pytest

from tests.runtimes.acp_agent import STDERR_LINE, FakeAgent


class _Client:
    async def session_update(self, **kwargs: Any) -> None:
        return None


class _Events:
    """Stands in for stderr, `os.close` and `time.sleep`, noting the order they are used."""

    def __init__(self) -> None:
        self.seen: list[str] = []

    def write(self, text: str) -> int:
        if text.strip():
            self.seen.append(f"stderr: {text.strip()}")
        return len(text)

    def flush(self) -> None:
        return None

    def close(self, fd: int) -> None:
        self.seen.append(f"close {fd}")

    def sleep(self, seconds: float) -> None:
        self.seen.append("sleep")


def test_the_agent_writes_stderr_before_it_closes_stdout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    events = _Events()
    monkeypatch.setattr(sys, "stderr", events)
    monkeypatch.setattr("os.close", events.close)
    monkeypatch.setattr("time.sleep", events.sleep)
    agent = FakeAgent(tmp_path / "agent.jsonl", "end_turn", fail="hang")
    agent.on_connect(_Client())  # pyrefly: ignore[bad-argument-type]

    asyncio.run(agent.prompt("session", []))

    lines = [seen for seen in events.seen if seen != "sleep"]
    assert lines.index(f"stderr: {STDERR_LINE}") < lines.index("close 1")
