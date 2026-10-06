"""What the `acp` adapter makes of the usage an agent's prompt response may
carry (spec: agent-usage-capture).

The agent is a real subprocess speaking the protocol over stdio
(`acp_agent.py`), whose `--usage` option puts a payload on the wire as an agent
could send it: the protocol's own counts, the same with a field no client knows
yet, or counts that are not numbers. Whatever it sends, the run's outcome is
the turn's, never the usage's.

Estimating tokens for an agent that reports none is not covered: the spec does
not say how estimation is switched on.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.runtimes import AgentRequest, AgentResult
from agent_build_kit.runtimes.acp import AcpRuntime
from agent_build_kit.usage import Usage
from tests.runtimes.acp_agent import ANSWER, COST_AMOUNT, SESSION, use_agent

REPORTED = Usage(
    input_tokens=7000,
    output_tokens=1500,
    cache_read_input_tokens=400,
    cache_creation_input_tokens=0,
)


@pytest.fixture
def worktree(tmp_path: Path) -> Path:
    path = tmp_path / "worktree"
    (path / "src").mkdir(parents=True)
    (path / "src" / "app.py").write_text("MARKER = None\n")
    return path


def call(
    worktree: Path, usage: str | None, tmp_path: Path, cost: str | None = None
) -> tuple[AgentResult, list[AgentResult], list[str]]:
    use_agent(tmp_path / "record.jsonl", usage=usage, cost=cost)
    results: list[AgentResult] = []
    lines: list[str] = []
    result = AcpRuntime().run(
        AgentRequest(
            prompt="Implement group 1 of add-marker.",
            role="implement",
            cwd=worktree,
            on_event=lines.append,
            on_result=results.append,
        )
    )
    return result, results, lines


def told_about_usage(lines: list[str]) -> list[str]:
    return [line for line in lines if "usage" in line.lower()]


def test_a_response_carrying_usage_is_recorded_as_reported(tmp_path: Path, worktree: Path) -> None:
    result, seen, lines = call(worktree, "reported", tmp_path)

    assert seen == [result]
    assert result.ok
    assert result.usage == REPORTED
    assert result.usage_source == "reported"
    assert result.cost_usd is None, "no usage_update came, so no cost was reported"
    assert told_about_usage(lines) == []


def test_a_response_without_usage_is_recorded_as_none_with_every_figure_absent(
    tmp_path: Path, worktree: Path
) -> None:
    result, seen, lines = call(worktree, None, tmp_path)

    assert seen == [result]
    assert result.ok
    assert result.usage is None
    assert result.cost_usd is None
    assert result.usage_source == "none"
    assert told_about_usage(lines) == []


@pytest.mark.parametrize("usage", ["reported", "extra", "malformed", None])
def test_no_replayed_payload_fails_the_run(
    usage: str | None, tmp_path: Path, worktree: Path
) -> None:
    result, seen, _ = call(worktree, usage, tmp_path)

    assert result.ok, result.error
    assert result.text == ANSWER
    assert result.turns == 1
    assert seen == [result]


def test_an_unknown_field_leaves_the_known_figures_recorded(tmp_path: Path, worktree: Path) -> None:
    result, _, lines = call(worktree, "extra", tmp_path)

    assert result.usage == REPORTED
    assert result.usage_source == "reported"
    assert told_about_usage(lines) == []


def test_a_malformed_payload_degrades_to_none_and_says_so_once(
    tmp_path: Path, worktree: Path
) -> None:
    result, _, lines = call(worktree, "malformed", tmp_path)

    assert result.ok
    assert result.usage is None
    assert result.usage_source == "none"
    assert len(told_about_usage(lines)) == 1


def test_a_usage_update_with_a_cost_in_dollars_is_recorded_as_the_cost(
    tmp_path: Path, worktree: Path
) -> None:
    result, seen, _ = call(worktree, None, tmp_path, cost="USD")

    assert seen == [result]
    assert result.cost_usd == COST_AMOUNT
    assert result.usage_source == "reported"


def test_a_cost_in_another_currency_is_left_absent(tmp_path: Path, worktree: Path) -> None:
    result, _, _ = call(worktree, "reported", tmp_path, cost="EUR")

    assert result.cost_usd is None
    assert result.usage == REPORTED
    assert result.usage_source == "reported"


def test_every_result_carries_the_session_the_agent_issued(tmp_path: Path, worktree: Path) -> None:
    result, seen, _ = call(worktree, None, tmp_path)

    assert result.session_id == SESSION
    assert seen[0].session_id == SESSION


def test_a_failed_turn_carries_its_session_too(tmp_path: Path, worktree: Path) -> None:
    use_agent(tmp_path / "record.jsonl", stop="max_tokens")

    result = AcpRuntime().run(
        AgentRequest(prompt="Implement group 1.", role="implement", cwd=worktree)
    )

    assert not result.ok
    assert result.session_id == SESSION
