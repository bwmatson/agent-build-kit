"""Each tier 1 command's duration is a `span` line in the usage ledger, under
its command (spec: unit-time-accounting). The command runner is the faked
boundary; the clock is a fake one it advances."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.wiring import build_tier1
from tests.fake_clock import FakeClock, install, span_lines


def test_a_tier_one_command_that_runs_for_45_seconds_is_recorded_under_its_command(
    tmp_path: Path, workspace: Installation, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock: FakeClock = install(monkeypatch)
    ran: list[list[str]] = []

    def run(command: list[str], *, cwd: Path) -> subprocess.CompletedProcess:
        ran.append(command)
        clock.advance(45 if len(ran) == 1 else 3)
        return subprocess.CompletedProcess(command, 0, "", "")

    repo = tmp_path / "plain"
    (repo / "tests").mkdir(parents=True)
    (repo / "pyproject.toml").write_text("[project]\nname = 'x'\n")

    passed, _ = build_tier1(run=run, changed=lambda *a: ["tests/test_x.py"])(cwd=repo, base="main")

    assert passed
    assert len(ran) >= 2
    by_command = {s["command"]: s for s in span_lines(workspace) if s.get("command")}
    assert set(by_command) == {" ".join(c) for c in ran}
    assert by_command[" ".join(ran[0])]["duration_ms"] == 45_000
    assert by_command[" ".join(ran[1])]["duration_ms"] == 3_000
    assert all(s["started"] and s["ended"] for s in by_command.values())
