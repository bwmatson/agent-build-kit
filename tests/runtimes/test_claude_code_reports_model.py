"""A Claude Code run reports the model its init event names, whether or not one was asked for
(spec: planner-model, the ledger records the model that ran)."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.runtimes import AgentRequest
from agent_build_kit.runtimes.claude_code import ClaudeCodeRuntime
from tests.runtimes.claude_cli import MODEL, FakeClaude, finished_build


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
