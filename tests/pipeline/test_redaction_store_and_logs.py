"""Text saved or printed by a run holds the replacement for a known secret value, and a
redaction that fails withholds the text."""

from __future__ import annotations

import asyncio
import json
import logging
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from agent_build_kit import config
from agent_build_kit.cli.pipeline import log
from agent_build_kit.graph.checkpointer import open_checkpointer, unit_graphs_path
from agent_build_kit.graph.unit import run_unit
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.run_log import RunLog
from agent_build_kit.pipeline.tier2 import Tier2Result, build_snapshot
from agent_build_kit.pipeline.transcript import Transcript, TranscriptEvent
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.usage_ledger import (
    LEDGER_NAME,
    UsageRecord,
    forget_told,
    record_call,
)
from agent_build_kit.pipeline.wiring import Tier2Session, build_tier1
from tests.factories import stored_unit, unit
from tests.redaction_fakes import FAILURE_MESSAGE, NAME, NOTICE, SECRET, known
from tests.runner_fakes import Recorder, make_runner

REPLACED = f"[redacted:{NAME}]"
START = datetime(2026, 9, 23, 22, 44, 5, tzinfo=UTC)


def _run_log(directory: Path) -> RunLog:
    return RunLog(directory, unit(), step="build", model="m", base="main", started=START)


def _transcript(directory: Path, *, limit: int = 20000) -> Transcript:
    return Transcript(
        directory, unit(), node="implement", round=1, started=START, result_limit=limit, runs_kept=3
    )


def _only(directory: Path) -> str:
    (written,) = directory.iterdir()
    return written.read_text()


def _assert_one_failure_line(caplog: pytest.LogCaptureFixture) -> None:
    lines = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert len(lines) == 1, [r.getMessage() for r in caplog.records]
    shown = lines[0].getMessage()
    assert SECRET not in shown
    assert FAILURE_MESSAGE not in shown


def _record(outcome: str) -> UsageRecord:
    return UsageRecord(
        at="2026-01-01T10:00:00+00:00", unit="add-marker/1", node="implement", outcome=outcome
    )


def _ledger_path() -> Path:
    root = config.active_root()
    assert root is not None
    return Installation(config.active(), root).state_dir / LEDGER_NAME


def _tier_two(tmp_path: Path, output: str) -> Tier2Session:
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\n")
    return Tier2Session(
        unit(tier="tier2"),
        lock=tmp_path / "t2.lock",
        run=lambda command, **kw: subprocess.CompletedProcess(command, 1, output, ""),
        sha=lambda cwd: "abc1234",
    )


def test_saved_feedback_holds_the_replacement(tmp_path: Path) -> None:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([stored_unit()])

    with known():
        store.set_feedback("add-marker/1", f"tier 2 failed with {SECRET} in the output")

    assert store.get("add-marker/1").feedback == f"tier 2 failed with {REPLACED} in the output"
    assert SECRET not in (tmp_path / "units.json").read_text()


def test_a_failing_tier_two_is_saved_and_said_without_the_value(tmp_path: Path) -> None:
    logs = tmp_path / "unit-logs"
    tier_two = unit(tier="tier2")
    run_log = RunLog(
        logs, tier_two, step="build", model="m", base="main", started=datetime.now(UTC)
    )
    store = UnitStore(tmp_path / "units.json")
    store.upsert([tier_two])
    recorder = Recorder(store, tier2_ok=False)
    recorder.tier2_output = build_snapshot(
        Tier2Result(
            sha="abcdef1234567",
            passed=0,
            failed=1,
            skipped=0,
            duration_seconds=1.5,
            command="uv run pytest -m local_stack",
            output=f"FAILED tests/live/test_it.py - Scratch(env={SECRET})",
        )
    )
    runner = make_runner(store, recorder, tmp_path)

    async def go() -> None:
        async with open_checkpointer(unit_graphs_path(tmp_path / "state")) as saver:
            await run_unit(
                runner, tier_two, base="main", graph=[], saver=saver, run_log=run_log, tracer=None
            )

    with known():
        asyncio.run(go())

    feedback = store.get(tier_two.id).feedback
    assert SECRET not in feedback
    assert REPLACED in feedback
    written = _only(logs)
    assert SECRET not in written
    assert REPLACED in written


def test_a_run_log_line_and_a_whole_agent_reply_hold_the_replacement(tmp_path: Path) -> None:
    run_log = _run_log(tmp_path)

    with known():
        run_log.emit(f"implement: key is {SECRET}")
        run_log.emit(f"the agent said\nline two has {SECRET}\n{SECRET} again")

    written = _only(tmp_path)
    assert SECRET not in written
    assert written.count(REPLACED) == 3


def test_printed_output_holds_the_replacement(capsys: pytest.CaptureFixture[str]) -> None:
    with known():
        log(f"unit failed: {SECRET}")

    out = capsys.readouterr().out
    assert SECRET not in out
    assert REPLACED in out


def test_the_ledger_outcome_holds_the_replacement() -> None:
    forget_told()

    with known():
        record_call(_record(f"died: {SECRET}"), lambda message: None)

    written = _ledger_path().read_text()
    assert SECRET not in written
    assert json.loads(written.splitlines()[-1])["outcome"] == f"died: {REPLACED}"


def test_a_tool_result_with_the_value_before_the_limit_keeps_no_part_of_it(tmp_path: Path) -> None:
    # The limit falls inside the value, so a cut before redaction leaves half of it.
    transcript = _transcript(tmp_path, limit=40)

    with known():
        transcript.record(TranscriptEvent(kind="tool_result", text="x" * 30 + SECRET + "y" * 200))

    written = _only(tmp_path)
    assert SECRET not in written
    assert SECRET[:8] not in written
    assert REPLACED[:8] in written


def test_tier_two_output_with_the_value_across_the_cut_keeps_no_part_of_it(
    tmp_path: Path,
) -> None:
    session = _tier_two(tmp_path, "x" * 100 + SECRET + "y" * 3990)

    with known():
        session.run(cwd=tmp_path)

    assert session.result is not None
    assert SECRET[-8:] not in session.result.output
    assert SECRET[:8] not in session.result.output


def test_tier_one_output_holds_the_replacement(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\n")
    (tmp_path / "tests").mkdir()

    def failing(command: list[str], **kw) -> subprocess.CompletedProcess:
        return subprocess.CompletedProcess(command, 1, f"FAILED with {SECRET}", "")

    with known():
        passed, output = build_tier1(run=failing, changed=lambda *a: ["tests/test_x.py"])(
            cwd=tmp_path, base="main"
        )

    assert passed is False
    assert SECRET not in output
    assert REPLACED in output


def test_a_failed_redaction_withholds_feedback(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([stored_unit()])

    with known(broken=True):
        store.set_feedback("add-marker/1", f"output {SECRET}")

    assert store.get("add-marker/1").feedback == NOTICE
    _assert_one_failure_line(caplog)


def test_a_failed_redaction_withholds_a_run_log_line(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    run_log = _run_log(tmp_path)

    with known(broken=True):
        run_log.emit(f"output {SECRET}")

    written = _only(tmp_path)
    assert NOTICE in written
    assert SECRET not in written
    _assert_one_failure_line(caplog)


def test_a_failed_redaction_withholds_a_transcript_event(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    transcript = _transcript(tmp_path)

    with known(broken=True):
        transcript.record(TranscriptEvent(kind="text", text=f"said {SECRET}"))

    assert json.loads(_only(tmp_path))["text"] == NOTICE
    _assert_one_failure_line(caplog)


def test_a_failed_redaction_withholds_a_ledger_line(caplog: pytest.LogCaptureFixture) -> None:
    forget_told()

    with known(broken=True):
        record_call(_record(f"died: {SECRET}"), lambda message: None)

    written = _ledger_path().read_text().splitlines()[-1]
    assert NOTICE in written
    assert SECRET not in written
    _assert_one_failure_line(caplog)


def test_a_failed_redaction_leaves_the_tier_two_counts_and_verdict(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    session = _tier_two(tmp_path, f"1 failed, 3 passed in 1.00s {SECRET}")

    with known(broken=True):
        ok, _ = session.run(cwd=tmp_path)

    assert ok is False
    assert session.result is not None
    assert (session.result.passed, session.result.failed) == (3, 1)
    assert session.result.output == NOTICE
    _assert_one_failure_line(caplog)
