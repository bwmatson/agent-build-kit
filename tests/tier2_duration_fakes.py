"""Pytest output as the tier 2 command prints it with durations, for the tests of how
a tier 2 result records the time of each test."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.tier2 import TestTime, Tier2Result
from agent_build_kit.pipeline.usage_ledger import LEDGER_NAME
from tests.tier2_failure_fakes import checkout, gate

# `(seconds, phase, test id)`: what one line of pytest's `slowest durations` section holds.
Entry = tuple[float, str, str]

E2E = "tests/e2e/test_x.py"


def durations_output(*entries: Entry, hidden: int = 0, lines: tuple[str, ...] = ()) -> str:
    """The tail of a pytest run with `--durations=0`: the section in pytest's own layout
    (`<seconds>s <phase padded to 8> <id>`, slowest first), the note pytest prints when
    entries under the minimum are left out, then the summary line. `lines` follow the
    section, as a plugin's terminal summary does."""
    rows = [f"{seconds:.2f}s {phase:<8} {test}" for seconds, phase, test in entries]
    note = [f"({hidden} durations < 1s hidden.  Use -vv to show these durations.)"] * bool(hidden)
    section = ["=" * 29 + " slowest durations " + "=" * 29, *rows, *note, *lines]
    passed = len({test for _, phase, test in entries if phase == "call"}) or 1
    return "\n".join(
        [
            "============================= test session starts ==============================",
            f"collected {passed} items",
            "",
            *section,
            f"======================== {passed} passed in {sum(e[0] for e in entries):.2f}s ====",
            "",
        ]
    )


def sixteen_tests() -> list[Entry]:
    """One call of 100 s down to 85 s for each of sixteen tests, in scrambled order."""
    ordered = [(100.0 - n, "call", f"{E2E}::test_{n:02d}") for n in range(16)]
    return ordered[8:] + ordered[:8]


def time_line(
    test: str,
    phase: str,
    *,
    agent: dict[str, int] | None = None,
    calls: dict[str, int] | None = None,
    checks_ms: int = 0,
    other_ms: int = 0,
) -> str:
    """The `ABK-TIME` line a test suite prints for one phase of one test."""
    body = {
        "test": test,
        "phase": phase,
        "agent": agent or {},
        "calls": calls or {},
        "checks_ms": checks_ms,
        "other_ms": other_ms,
    }
    return f"ABK-TIME {json.dumps(body)}"


def run_tier2(tmp_path: Path, output: str, name: str = "first") -> Tier2Result:
    """The result of a tier 2 gate whose one command exits 0 printing `output`, run in a
    checkout of its own under `tmp_path`."""

    def run(command: list[str], **kwargs) -> subprocess.CompletedProcess:
        return subprocess.CompletedProcess(command, 0, output, "")

    where = tmp_path / name
    where.mkdir()
    session = gate(where, run)
    session.run(cwd=checkout(where))
    assert session.result is not None
    return session.result


def recorded_times(workspace: Installation) -> list[dict]:
    """The `test_time` lines of the active installation's usage ledger."""
    path = workspace.state_dir / LEDGER_NAME
    lines = path.read_text().splitlines() if path.exists() else []
    return [row for row in map(json.loads, lines) if row["kind"] == "test_time"]


def timed(seconds: float, test: str = f"{E2E}::test_a", phase: str = "call") -> TestTime:
    return TestTime(test=test, phase=phase, seconds=seconds)
