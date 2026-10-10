"""A call on the Claude Code runtime hands its caller what the run spent
(`AgentRequest.on_result`), whether it succeeded or failed, and says the figures
are the agent's own (spec: agent-usage-capture).

The `claude` process is faked at its boundary with the stream-json a real run
prints.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_build_kit.runtimes import AgentRateLimited, AgentRequest, AgentResult
from agent_build_kit.runtimes.claude_code import ClaudeCodeRuntime
from agent_build_kit.usage import Usage
from tests.runtimes.claude_cli import MODEL, SESSION, FakeClaude, finished_build

SPENT = Usage(
    input_tokens=4,
    output_tokens=212,
    cache_read_input_tokens=14671,
    cache_creation_input_tokens=1822,
)


def asking(cwd: Path, seen: list[AgentResult]) -> AgentRequest:
    return AgentRequest(
        prompt="Implement group 1 of add-marker.",
        role="implement",
        cwd=cwd,
        model=MODEL,
        on_result=seen.append,
    )


def test_a_successful_call_reports_its_usage_as_the_agent_s_own(tmp_path: Path) -> None:
    seen: list[AgentResult] = []
    fake = FakeClaude(stdout=finished_build(tmp_path, "done"))

    result = ClaudeCodeRuntime(execute=fake).run(asking(tmp_path, seen))

    assert seen == [result]
    assert result.ok
    assert result.usage == SPENT
    assert result.cumulative_cost_usd == 0.4127
    assert result.cost_usd is None, "the total is the session's, not the call's own spend"
    assert result.turns == 3
    assert result.duration_ms == 81234
    assert result.session_id == SESSION
    assert result.usage_source == "reported"


def test_a_failed_call_reports_its_figures_too(tmp_path: Path) -> None:
    *events, closing = finished_build(tmp_path, "done").splitlines()
    ended = json.loads(closing) | {
        "subtype": "error_max_turns",
        "is_error": True,
        "errors": ["reached the turn limit"],
    }
    del ended["result"]
    seen: list[AgentResult] = []
    fake = FakeClaude(stdout="\n".join([*events, json.dumps(ended)]) + "\n", returncode=1)

    result = ClaudeCodeRuntime(execute=fake).run(asking(tmp_path, seen))

    assert seen == [result]
    assert not result.ok
    assert result.usage == SPENT
    assert result.cumulative_cost_usd == 0.4127
    assert result.session_id == SESSION
    assert result.usage_source == "reported"


def test_a_run_whose_output_carries_no_result_event_reports_nothing_rather_than_zeros(
    tmp_path: Path,
) -> None:
    seen: list[AgentResult] = []
    fake = FakeClaude(stdout="the answer, as plain -p prints it\n")

    result = ClaudeCodeRuntime(execute=fake).run(asking(tmp_path, seen))

    assert seen == [result]
    assert result.usage is None
    assert result.cost_usd is None
    assert result.cumulative_cost_usd is None
    assert result.duration_ms is None
    assert result.usage_source == "none"


def test_an_event_carrying_only_a_session_id_is_recorded_as_none(tmp_path: Path) -> None:
    *events, closing = finished_build(tmp_path, "done").splitlines()
    bare = json.loads(closing)
    for figure in ("usage", "total_cost_usd", "duration_ms", "duration_api_ms", "num_turns"):
        del bare[figure]
    seen: list[AgentResult] = []
    fake = FakeClaude(stdout="\n".join([*events, json.dumps(bare)]) + "\n")

    result = ClaudeCodeRuntime(execute=fake).run(asking(tmp_path, seen))

    assert seen == [result]
    assert result.session_id == SESSION
    assert result.usage is None
    assert result.cost_usd is None
    assert result.cumulative_cost_usd is None
    assert result.usage_source == "none"


def test_a_call_ended_by_the_usage_limit_still_reports_what_it_spent(tmp_path: Path) -> None:
    seen: list[AgentResult] = []
    fake = FakeClaude(
        stdout=finished_build(tmp_path, "done"),
        returncode=1,
        stderr="Claude AI usage limit reached|1900000000",
    )

    with pytest.raises(AgentRateLimited):
        ClaudeCodeRuntime(execute=fake).run(asking(tmp_path, seen))

    assert len(seen) == 1
    assert not seen[0].ok
    assert "usage limit reached" in seen[0].error
    assert seen[0].cumulative_cost_usd == 0.4127
    assert seen[0].usage == SPENT
    assert seen[0].usage_source == "reported"
