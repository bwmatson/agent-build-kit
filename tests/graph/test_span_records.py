"""A unit's nodes and usage pauses leave `span` lines in the usage ledger, with
UTC stamps, and nothing the ledger does can fail a run (spec: unit-time-accounting).

Time is a fake clock the agent callables advance; the thread is the real one."""

from __future__ import annotations

import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.stack_runner import RunStatus
from agent_build_kit.pipeline.wiring import build_tier1
from tests.factories import unit
from tests.fake_clock import START, FakeClock, install, span_lines
from tests.graph_driver import fresh, tick
from tests.runner_fakes import Recorder

WINDOW = "session usage at 88%"


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> FakeClock:
    return install(monkeypatch)


def timed(recorder: Recorder, clock: FakeClock, *, tests: float = 0, raises: bool = False) -> Any:
    """A `run_claude` that takes `tests` seconds on the tests node, and fails
    after them when asked."""

    def run_claude(prompt: str, **kwargs: Any) -> str:
        answer = recorder.claude(prompt, **kwargs)
        if "test tasks" in prompt:
            clock.advance(tests)
            if raises:
                raise RuntimeError("boom")
        return answer

    return run_claude


def at(stamp: str) -> datetime:
    parsed = datetime.fromisoformat(stamp)
    assert parsed.utcoffset() == timedelta(0), f"{stamp} is not UTC"
    return parsed


def test_a_node_that_runs_for_a_known_time_writes_one_span_naming_it(
    tmp_path: Path, workspace: Installation, clock: FakeClock
) -> None:
    recorder = fresh(tmp_path)

    outcome = tick(tmp_path, recorder, run_claude=timed(recorder, clock, tests=7))

    assert outcome.status == RunStatus.OPEN
    (span,) = [s for s in span_lines(workspace) if s["node"] == "tests" and not s.get("waited")]
    assert span["unit"] == "add-marker/1"
    assert span["change"] == unit().change
    assert span["round"] == 0
    assert at(span["started"]) == START
    assert at(span["ended"]) == START + timedelta(seconds=7)
    assert span["duration_ms"] == 7000
    assert span["outcome"] == "ok"
    nodes = {s["node"] for s in span_lines(workspace)}
    assert {"prepare", "implement", "review"} <= nodes, "every node leaves its span"


def test_a_node_that_raises_still_writes_its_span_with_the_failure_outcome(
    tmp_path: Path, workspace: Installation, clock: FakeClock
) -> None:
    recorder = fresh(tmp_path)

    with pytest.raises(RuntimeError, match="boom"):
        tick(tmp_path, recorder, run_claude=timed(recorder, clock, tests=2, raises=True))

    (span,) = [s for s in span_lines(workspace) if s["node"] == "tests"]
    assert span["outcome"] == "error"
    assert span["duration_ms"] == 2000
    assert at(span["ended"]) == START + timedelta(seconds=2)


def test_a_gate_interrupt_then_resume_records_the_pause_as_usage_pause(
    tmp_path: Path, workspace: Installation, clock: FakeClock
) -> None:
    recorder = fresh(tmp_path)
    tick(tmp_path, recorder, may_start=lambda: (False, WINDOW), resume_at=lambda: START)
    clock.advance(3600)

    outcome = tick(tmp_path, recorder, may_start=lambda: (True, "usage fine"))

    assert outcome.status == RunStatus.OPEN
    paused = [s for s in span_lines(workspace) if s.get("waited") == "usage_pause"]
    assert paused, "the pause left a record"
    assert {s["unit"] for s in paused} == {"add-marker/1"}
    assert {s["node"] for s in paused} == {"tests"}, "where the thread was waiting"
    assert max(s["duration_ms"] for s in paused) == 3_600_000
    assert max(at(s["ended"]) for s in paused) == START + timedelta(hours=1)


def test_a_ledger_that_cannot_be_written_changes_nothing_about_the_run(
    tmp_path: Path, workspace: Installation, clock: FakeClock
) -> None:
    # A file where the state directory should be: no append can succeed.
    workspace.state_dir.write_text("not a directory")
    recorder = fresh(tmp_path)

    paused = tick(tmp_path, recorder, may_start=lambda: (False, WINDOW), resume_at=lambda: START)
    clock.advance(60)
    outcome = tick(tmp_path, recorder, run_claude=timed(recorder, clock, tests=5))

    assert paused.status == RunStatus.PAUSED
    assert outcome.status == RunStatus.OPEN
    assert recorder.store.get("add-marker/1").state == "in_review"
    assert workspace.state_dir.read_text() == "not a directory"
    told = [line for line in recorder.logged if "ledger" in line.lower()]
    assert len(told) == 1, "spans failed to record; the failure is reported once"


def test_a_node_that_raises_raises_the_same_error_when_the_ledger_cannot_be_written(
    tmp_path: Path, workspace: Installation, clock: FakeClock
) -> None:
    workspace.state_dir.write_text("not a directory")
    recorder = fresh(tmp_path)

    with pytest.raises(RuntimeError, match="boom"):
        tick(tmp_path, recorder, run_claude=timed(recorder, clock, tests=2, raises=True))

    assert [line for line in recorder.logged if "ledger" in line.lower()], "and it said so"


def tier_one_commands(tmp_path: Path, workspace: Installation, clock: FakeClock, **overrides: Any):
    tree = tmp_path / "tree"
    (tree / "tests").mkdir(parents=True)
    (tree / "pyproject.toml").write_text("[project]\nname = 'x'\n")

    def run(command: list[str], *, cwd: Path) -> subprocess.CompletedProcess:
        clock.advance(2)
        return subprocess.CompletedProcess(command, 0, "", "")

    recorder = fresh(tmp_path)
    tier1 = build_tier1(run=run, changed=lambda *a: ["tests/test_x.py"])
    tick(tmp_path, recorder, run_tier1=tier1, **overrides)
    return [s for s in span_lines(workspace) if s.get("command")]


def test_a_tier_one_command_run_by_the_checks_node_carries_its_node_and_round(
    tmp_path: Path, workspace: Installation, clock: FakeClock
) -> None:
    commands = tier_one_commands(tmp_path, workspace, clock)

    assert commands
    assert {(s["unit"], s["change"], s["node"], s["round"]) for s in commands} == {
        ("add-marker/1", unit().change, "checks", 1)
    }


def test_a_tier_one_command_run_by_the_tier_one_node_carries_that_node(
    tmp_path: Path, workspace: Installation, clock: FakeClock
) -> None:
    commands = tier_one_commands(tmp_path, workspace, clock, branch_commits=lambda cwd, base: 0)

    assert commands
    assert {(s["unit"], s["change"], s["node"], s["round"]) for s in commands} == {
        ("add-marker/1", unit().change, "tier1", 0)
    }
