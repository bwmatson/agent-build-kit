"""A Claude Code run reports the model its init event names, whether or not one was asked for
(spec: planner-model, the ledger records the model that ran)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_build_kit.runtimes import AgentRateLimited, AgentRequest, AgentResult
from agent_build_kit.runtimes.claude_code import ClaudeCodeRuntime
from tests.runtimes.claude_cli import MODEL, FakeClaude, finished_build, refused, stream


def test_a_run_with_no_model_reports_the_model_the_init_event_named(tmp_path: Path) -> None:
    fake = FakeClaude(stdout=finished_build(tmp_path, "done"))
    request = AgentRequest(prompt="Plan.", role="generic", cwd=tmp_path)

    result = ClaudeCodeRuntime(execute=fake).run(request)

    assert "--model" not in fake.calls[0][0]
    assert result.reported_model == MODEL


def test_a_run_with_a_model_reports_the_model_that_ran(tmp_path: Path) -> None:
    fake = FakeClaude(stdout=finished_build(tmp_path, "done"))
    request = AgentRequest(prompt="Plan.", role="generic", cwd=tmp_path, model="opus")

    result = ClaudeCodeRuntime(execute=fake).run(request)

    assert result.reported_model == MODEL


def test_the_init_event_wins_over_the_model_an_assistant_message_names(tmp_path: Path) -> None:
    events = [json.loads(line) for line in finished_build(tmp_path, "done").splitlines()]
    for event in events:
        if event["type"] == "assistant":
            event["message"]["model"] = "claude-haiku-5-5"
    fake = FakeClaude(stdout=stream(*events))
    request = AgentRequest(prompt="Plan.", role="generic", cwd=tmp_path)

    result = ClaudeCodeRuntime(execute=fake).run(request)

    assert result.reported_model == MODEL


def test_a_run_cut_off_before_any_answer_still_reports_the_init_event_model(
    tmp_path: Path,
) -> None:
    fake = FakeClaude(stdout=refused(tmp_path, "the build broke"), returncode=1)
    request = AgentRequest(prompt="Plan.", role="generic", cwd=tmp_path)

    result = ClaudeCodeRuntime(execute=fake).run(request)

    assert not result.ok
    assert result.reported_model == MODEL


def test_a_refused_run_records_the_init_event_model_in_its_spend(tmp_path: Path) -> None:
    fake = FakeClaude(
        stdout=refused(tmp_path, "Claude AI usage limit reached|1919763200"), returncode=1
    )
    seen: list[AgentResult] = []
    request = AgentRequest(prompt="Plan.", role="generic", cwd=tmp_path, on_result=seen.append)

    with pytest.raises(AgentRateLimited):
        ClaudeCodeRuntime(execute=fake).run(request)

    (told,) = seen
    assert told.reported_model == MODEL
