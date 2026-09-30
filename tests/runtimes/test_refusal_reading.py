"""Telling a refusal from a run that merely talks about one.

A finished `claude` run's transcript is the run's own prose, the files it read
and every event's ids and counts. A build of rate-limit code has the words of a
usage refusal all over a perfectly good run, so only how the run ended — its
exit, its result event, its stderr — may say whether the account refused.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from agent_build_kit.pipeline.usage_guard import rate_limit_reset
from agent_build_kit.runtimes import AgentRateLimited, AgentRequest, ToolPolicy
from agent_build_kit.runtimes.claude_code import ClaudeCodeRuntime
from tests.runtimes.claude_cli import FakeClaude, failed_build, finished_build, refused

REFUSAL = "Claude AI usage limit reached|1919763200"


def _request(cwd: Path) -> AgentRequest:
    return AgentRequest(
        prompt="Implement group 1 of add-marker.",
        role="implement",
        cwd=cwd,
        add_dirs=(cwd / "specs",),
        model="opus",
        allowed_tools="Read Edit Write",
        policy=ToolPolicy(specs_dir=cwd / "specs"),
        on_event=lambda line: None,
    )


def test_a_successful_run_whose_answer_quotes_a_refusal_is_not_refused(tmp_path: Path) -> None:
    answer = f"Added the guard. It now pauses on '{REFUSAL}' and on HTTP 429 rate_limit_error."
    fake = FakeClaude(stdout=finished_build(tmp_path, answer), returncode=0)

    result = ClaudeCodeRuntime(execute=fake).run(_request(tmp_path))

    assert result.ok is True
    assert result.text == answer
    assert result.stop_reason == "success"


def test_a_successful_run_that_read_and_discussed_refusals_is_not_refused(tmp_path: Path) -> None:
    """The whole failed-build transcript — the usage guard read back, prose about
    the rate limit, "429" in the session — around a result that succeeded."""
    events = [json.loads(line) for line in failed_build(tmp_path, "unused").splitlines()]
    events[-1] = json.loads(finished_build(tmp_path, "Guard reviewed; no change.").splitlines()[-1])
    stdout = "".join(json.dumps(event) + "\n" for event in events)
    assert "429" in stdout
    assert "usage limit reached" in stdout

    result = ClaudeCodeRuntime(execute=FakeClaude(stdout=stdout, returncode=0)).run(
        _request(tmp_path)
    )

    assert result.ok is True
    assert result.text == "Guard reviewed; no change."


def test_a_real_refusal_is_raised_with_its_reset_read_from_the_message(tmp_path: Path) -> None:
    fake = FakeClaude(stdout=refused(tmp_path, REFUSAL), returncode=1)

    with pytest.raises(AgentRateLimited) as caught:
        ClaudeCodeRuntime(execute=fake).run(_request(tmp_path))

    assert caught.value.resets_at == datetime.fromtimestamp(1919763200, UTC)


def test_a_real_refusal_without_a_reset_is_raised_with_none(tmp_path: Path) -> None:
    fake = FakeClaude(stdout=refused(tmp_path, "API Error: 429 rate_limit_error"), returncode=1)

    with pytest.raises(AgentRateLimited) as caught:
        ClaudeCodeRuntime(execute=fake).run(_request(tmp_path))

    assert caught.value.resets_at is None


def test_a_failed_run_whose_stderr_holds_digits_that_spell_429_is_not_refused(
    tmp_path: Path,
) -> None:
    """A commit hash or a millisecond count is not an HTTP status."""
    fake = FakeClaude(
        stdout=failed_build(tmp_path, "Execution error: the Edit tool could not write the file"),
        returncode=1,
        stderr="error: hook rejected commit 3a4290f after 14290ms",
    )

    result = ClaudeCodeRuntime(execute=fake).run(_request(tmp_path))

    assert result.ok is False
    assert "3a4290f" in result.error


@pytest.mark.parametrize(
    "message",
    [
        "Claude AI usage limit reached|1919763200",
        "You've hit your usage limit reached|1919763200 — resets soon",
        'API Error: 429 {"type":"error","error":{"type":"rate_limit_error"}}',
    ],
)
def test_the_messages_a_refusal_arrives_as_are_recognised(message: str) -> None:
    assert rate_limit_reset(message) is not False


def test_the_reset_time_is_read_where_present_and_absent_otherwise() -> None:
    assert rate_limit_reset(REFUSAL) == datetime.fromtimestamp(1919763200, UTC)
    assert rate_limit_reset("API Error: 429 rate_limit_error") is None


@pytest.mark.parametrize(
    "text",
    [
        "",
        "Execution error: the Edit tool could not write the file",
        "error: hook rejected commit 3a4290f after 14290ms",
        "collected 4290 items",
    ],
)
def test_text_that_is_not_a_refusal_is_not_read_as_one(text: str) -> None:
    assert rate_limit_reset(text) is False
