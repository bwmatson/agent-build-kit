"""A call on the Claude Code runtime hands its caller what the run spent
(`AgentRequest.on_result`), whether it succeeded or failed, and says the figures
are the agent's own (spec: agent-usage-capture).

The `claude` process is faked at its boundary with the stream-json a real run
prints.
"""

from __future__ import annotations

import json
from pathlib import Path

from agent_build_kit.runtimes import AgentRequest, AgentResult
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
    assert result.cost_usd == 0.4127
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
    assert result.cost_usd == 0.4127
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
    assert result.duration_ms is None
    assert result.usage_source == "none"
