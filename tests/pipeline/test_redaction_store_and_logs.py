"""Text saved or printed by a run holds the replacement for a known secret value, and a
redaction that fails withholds the text."""

from __future__ import annotations

import json
import logging
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from agent_build_kit import config
from agent_build_kit.cli.pipeline import log
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.run_log import RunLog
from agent_build_kit.pipeline.spans import Span
from agent_build_kit.pipeline.tier2 import Tier2Result, build_snapshot
from agent_build_kit.pipeline.transcript import Transcript, TranscriptEvent
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.usage_ledger import (
    LEDGER_NAME,
    UsageRecord,
    forget_told,
    read_ledger,
    record_call,
    record_line,
)
from agent_build_kit.pipeline.wiring import Tier2Session, build_tier1
from tests.factories import stored_unit, unit
from tests.redaction_fakes import FAILURE_MESSAGE, NAME, NOTICE, SECRET, known
from tests.tier2_failure_fakes import gate, run_failing_tier2, run_returning

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


def _assert_one_failure_line(caplog: pytest.LogCaptureFixture, where: str) -> None:
    lines = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert len(lines) == 1, [r.getMessage() for r in caplog.records]
    shown = lines[0].getMessage()
    assert where in shown
    assert "RuntimeError" in shown
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
    return gate(tmp_path, run_returning(output), root=tmp_path)


def test_saved_feedback_holds_the_replacement(tmp_path: Path) -> None:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([stored_unit()])

    with known():
        store.set_feedback("add-marker/1", f"tier 2 failed with {SECRET} in the output")

    assert store.get("add-marker/1").feedback == f"tier 2 failed with {REPLACED} in the output"
    assert SECRET not in (tmp_path / "units.json").read_text()


def test_a_failing_tier_two_is_saved_and_said_without_the_value(tmp_path: Path) -> None:
    snapshot = build_snapshot(
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

    with known():
        feedback, logs = run_failing_tier2(tmp_path, snapshot)

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
    _assert_one_failure_line(caplog, "feedback")


def test_a_failed_redaction_withholds_a_run_log_line(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    run_log = _run_log(tmp_path)

    with known(broken=True):
        run_log.emit(f"output {SECRET}")

    written = _only(tmp_path)
    assert NOTICE in written
    assert SECRET not in written
    _assert_one_failure_line(caplog, "run log")


def test_a_failed_redaction_withholds_a_transcript_event(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    transcript = _transcript(tmp_path)

    with known(broken=True):
        transcript.record(TranscriptEvent(kind="text", text=f"said {SECRET}"))

    assert json.loads(_only(tmp_path))["text"] == NOTICE
    _assert_one_failure_line(caplog, "transcript")


def test_a_failed_redaction_withholds_a_ledger_line(caplog: pytest.LogCaptureFixture) -> None:
    forget_told()

    with known(broken=True):
        record_call(_record(f"died: {SECRET}"), lambda message: None)

    written = _ledger_path().read_text().splitlines()[-1]
    assert NOTICE in written
    assert SECRET not in written
    _assert_one_failure_line(caplog, "ledger")


def test_a_failed_redaction_keeps_the_figures_of_a_ledger_record(
    caplog: pytest.LogCaptureFixture,
) -> None:
    forget_told()
    record = UsageRecord(
        at="2026-01-01T10:00:00+00:00",
        unit="add-marker/1",
        node="implement",
        session_id="sess-1",
        input_tokens=120,
        outcome=f"died: {SECRET}",
    )

    with known(broken=True):
        record_call(record, lambda message: None)

    assert SECRET not in _ledger_path().read_text()
    (read,) = read_ledger(_ledger_path())
    assert (read.unit, read.input_tokens, read.outcome) == ("add-marker/1", 120, NOTICE)
    _assert_one_failure_line(caplog, "ledger")


def test_a_failed_redaction_logs_one_line_for_a_tier_two_of_several_commands(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    (tmp_path / "pyproject.toml").write_text('[tool.uv.workspace]\nmembers = ["svc-a", "svc-b"]\n')
    for member in ("svc-a", "svc-b"):
        (tmp_path / member / "tests").mkdir(parents=True)
        (tmp_path / member / "pyproject.toml").write_text(f'[project]\nname = "{member}"\n')
    session = Tier2Session(
        unit(tier="tier2"),
        lock=tmp_path / "t2.lock",
        timeout=5,
        run=lambda command, **kw: subprocess.CompletedProcess(
            command, 1, f"1 failed in 1.00s {SECRET}", ""
        ),
        sha=lambda cwd: "abc1234",
    )

    with known(broken=True):
        session.run(cwd=tmp_path)

    _assert_one_failure_line(caplog, "tier-2 output")


def test_a_failed_redaction_withholds_every_text_field_of_a_span(
    caplog: pytest.LogCaptureFixture,
) -> None:
    forget_told()
    span = Span(
        at="2026-01-01T10:00:00+00:00",
        started="2026-01-01T10:00:00+00:00",
        ended="2026-01-01T10:00:01+00:00",
        duration_ms=1000,
        cause=f"waited for {SECRET}",
    )

    with known(broken=True):
        record_line(span, lambda message: None)

    written = _ledger_path().read_text().splitlines()[-1]
    assert SECRET not in written
    assert json.loads(written)["cause"] == NOTICE
    _assert_one_failure_line(caplog, "ledger")


def test_a_value_with_a_quote_in_it_is_replaced_in_the_ledger() -> None:
    forget_told()
    value = 'pa"ss\\word-0001'

    with known({NAME: value}):
        record_call(_record(f"died: {value}"), lambda message: None)

    written = _ledger_path().read_text().splitlines()[-1]
    assert json.loads(written)["outcome"] == f"died: {REPLACED}"
    assert "pa" + '\\"' + "ss" not in written


def test_a_tool_call_input_holds_the_replacement_at_every_depth(tmp_path: Path) -> None:
    transcript = _transcript(tmp_path)

    with known():
        transcript.record(
            TranscriptEvent(
                kind="tool_call",
                tool="Bash",
                input={"command": f"echo {SECRET}", "nested": {"k": [SECRET]}},
            )
        )

    written = _only(tmp_path)
    assert SECRET not in written
    recorded = json.loads(written)["input"]
    assert recorded == {"command": f"echo {REPLACED}", "nested": {"k": [REPLACED]}}


def test_a_passing_tier_two_command_is_redacted_before_its_output_is_cut(
    tmp_path: Path,
) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\n")
    out = "1 passed in 0.10s\n" + "x" * 100 + SECRET + "y" * 1490
    session = Tier2Session(
        unit(tier="tier2"),
        lock=tmp_path / "t2.lock",
        timeout=5,
        run=lambda command, **kw: subprocess.CompletedProcess(command, 0, out, ""),
        sha=lambda cwd: "abc1234",
    )

    with known():
        session.run(cwd=tmp_path)

    assert session.result is not None
    assert SECRET[:8] not in session.result.output
    assert SECRET[-8:] not in session.result.output


def test_verification_detail_holds_the_replacement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from agent_build_kit.cli import pipeline as pipeline_cli
    from agent_build_kit.pipeline.verify import Verification

    monkeypatch.setattr(
        pipeline_cli,
        "verify_change",
        lambda *a, **k: Verification(change="add-marker", passed=False, detail=f"down: {SECRET}"),
    )
    root = config.active_root()
    assert root is not None

    with known():
        outcome = pipeline_cli.verify_one(Installation(config.active(), root), "add-marker", [])

    assert outcome.detail == f"down: {REPLACED}"


def test_a_failed_redaction_leaves_the_tier_two_counts_and_verdict(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    session = _tier_two(tmp_path, f"1 failed, 3 passed in 1.00s {SECRET}")

    with known(broken=True):
        ok, _ = session.run(cwd=tmp_path)

    assert ok is False
    assert session.result is not None
    assert (session.result.passed, session.result.failed) == (3, 1)
    # The command's own header stays; what it printed is withheld.
    assert session.result.output.endswith(f"\n{NOTICE}")
    assert SECRET not in session.result.output
    _assert_one_failure_line(caplog, "tier-2 output")
