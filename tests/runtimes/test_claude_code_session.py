"""A Claude Code run reports its session as soon as the init event names it and
continues an earlier one when asked, or says it cannot."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.runtimes import AgentRequest, claude_code
from agent_build_kit.runtimes.base import SessionUnavailable
from agent_build_kit.runtimes.claude_code import ClaudeCodeRuntime
from tests.runtimes.claude_cli import SESSION, FakeClaude, finished_build, refused, stream


def request(cwd: Path, **fields: object) -> AgentRequest:
    return AgentRequest(prompt="Continue.", role="implement", cwd=cwd, **fields)  # pyrefly: ignore


def test_the_runtime_declares_that_it_resumes_sessions() -> None:
    assert claude_code.RUNTIME.supports_session_resume


def test_a_session_to_continue_is_passed_as_resume(tmp_path: Path) -> None:
    argv = claude_code.build_argv(request(tmp_path, resume_session=SESSION))

    assert argv[argv.index("--resume") + 1] == SESSION


def test_a_run_with_no_session_to_continue_passes_no_resume(tmp_path: Path) -> None:
    assert "--resume" not in claude_code.build_argv(request(tmp_path))


def test_the_session_id_is_reported_from_the_init_event(tmp_path: Path) -> None:
    told: list[str] = []
    fake = FakeClaude(stdout=finished_build(tmp_path, "done"))

    ClaudeCodeRuntime(execute=fake).run(request(tmp_path, on_session=told.append))

    assert told[0] == SESSION


def test_only_the_init_event_reports_the_session(tmp_path: Path) -> None:
    told: list[str] = []
    other = {"type": "system", "subtype": "status", "session_id": SESSION}
    fake = FakeClaude(stdout=stream(other, other) + finished_build(tmp_path, "done"))

    ClaudeCodeRuntime(execute=fake).run(request(tmp_path, on_session=told.append))

    assert told == [SESSION], "one report, so one checkpoint, however many system events"


def test_a_session_the_cli_cannot_find_is_unavailable(tmp_path: Path) -> None:
    fake = FakeClaude(
        stdout=refused(tmp_path, f"No conversation found with session ID: {SESSION}"),
        returncode=1,
    )

    with pytest.raises(SessionUnavailable):
        ClaudeCodeRuntime(execute=fake).run(request(tmp_path, resume_session=SESSION))
