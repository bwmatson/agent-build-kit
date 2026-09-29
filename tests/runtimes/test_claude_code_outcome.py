"""How the Claude Code adapter reads what the CLI hands back.

Every call site used to interpret a finished `claude` process for itself, and
three of them disagreed. The adapter is now the one place that does, and the
four outcomes stay apart:

- **An answer.** The streamed `result` event's text — what plain `-p` would
  have printed — with each step of progress passed on as it happens.
- **A spent usage window**, raised with its reset time so the pipeline pauses
  until then instead of failing the unit.
- **An interruption.** The process was killed, which says nothing about the
  work; the unit is reclaimed, not failed.
- **Anything else** is a failed result, not an exception a caller has to
  guess the meaning of.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from agent_build_kit.runtimes import (
    AgentInterrupted,
    AgentRateLimited,
    AgentRequest,
    ToolPolicy,
)
from agent_build_kit.runtimes.claude_code import ClaudeCodeRuntime
from tests.runtimes.claude_cli import FakeClaude, finished_build, refused, stream


def _request(cwd: Path, *, on_event=None) -> AgentRequest:
    return AgentRequest(
        prompt="Implement group 1 of add-marker.",
        role="implement",
        cwd=cwd,
        add_dirs=(cwd / "specs",),
        model="opus",
        allowed_tools="Read Edit Write",
        policy=ToolPolicy(specs_dir=cwd / "specs"),
        on_event=on_event or (lambda line: None),
    )


def test_a_streamed_run_answers_with_the_result_event_s_text(tmp_path: Path) -> None:
    """The review step parses this answer as JSON, so it must be the result
    text alone, not the stream it arrived in."""
    answer = '{"approved": true, "feedback": "", "needs_human": false}'
    fake = FakeClaude(stdout=finished_build(tmp_path, answer))

    result = ClaudeCodeRuntime(execute=fake).run(_request(tmp_path))

    assert result.ok is True
    assert result.text == answer
    assert json.loads(result.text)["approved"] is True
    assert result.raw == fake.stdout
    assert result.error == ""


def test_each_step_of_a_streamed_run_reaches_the_progress_callback(tmp_path: Path) -> None:
    """The tick log shows what a twenty-minute run is doing: what the model
    says and which tool it calls on what, relative to the worktree, whose
    absolute path would be the same long prefix on every line."""
    lines: list[str] = []
    fake = FakeClaude(stdout=finished_build(tmp_path, "done"))

    ClaudeCodeRuntime(execute=fake).run(_request(tmp_path, on_event=lines.append))

    said = [line.strip() for line in lines]
    assert said[0] == "claude started (claude-opus-5-5)"
    assert "says: I'll add the marker to the app module." in said
    assert "Edit src/app.py" in said
    assert said[-1] == "claude done — 3 turns, 1m21s"
    assert not any(str(tmp_path) in line for line in lines)


def test_a_spent_usage_window_raises_with_its_reset_time(tmp_path: Path) -> None:
    fake = FakeClaude(
        stdout=refused(tmp_path, "Claude AI usage limit reached|1919763200"), returncode=1
    )

    with pytest.raises(AgentRateLimited) as caught:
        ClaudeCodeRuntime(execute=fake).run(_request(tmp_path))

    assert caught.value.resets_at == datetime.fromtimestamp(1919763200, UTC)


def test_a_refusal_that_does_not_say_when_it_lifts_still_raises(tmp_path: Path) -> None:
    """No timestamp must not read as "not rate limited": the live usage
    reading supplies the time instead."""
    fake = FakeClaude(
        stdout=refused(tmp_path, "API Error: 429 rate_limit_error"),
        returncode=1,
        stderr="",
    )

    with pytest.raises(AgentRateLimited) as caught:
        ClaudeCodeRuntime(execute=fake).run(_request(tmp_path))

    assert caught.value.resets_at is None


def test_a_process_killed_by_a_signal_is_an_interruption(tmp_path: Path) -> None:
    """A run killed seconds in says nothing about the work; failing the unit
    would untick its tasks for no reason."""
    started = stream(json.loads(finished_build(tmp_path, "done").splitlines()[0]))
    fake = FakeClaude(stdout=started, returncode=-9)

    with pytest.raises(AgentInterrupted, match="9"):
        ClaudeCodeRuntime(execute=fake).run(_request(tmp_path))


def test_any_other_failed_exit_is_a_failed_result(tmp_path: Path) -> None:
    """Not an exception: the caller decides what a broken run means for its
    step, and is told why."""
    fake = FakeClaude(returncode=1, stderr="error: unknown option '--frobnicate'\n")

    result = ClaudeCodeRuntime(execute=fake).run(_request(tmp_path))

    assert result.ok is False
    assert "unknown option '--frobnicate'" in result.error


def test_a_failure_is_never_read_as_a_rate_limit_or_an_interruption(tmp_path: Path) -> None:
    fake = FakeClaude(returncode=2, stderr="error: could not resolve host github.com")

    result = ClaudeCodeRuntime(execute=fake).run(_request(tmp_path))

    assert result.ok is False
    assert "could not resolve host" in result.error
