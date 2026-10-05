"""What an agent run reports when telemetry is on: an agent span with the
runtime, model, role, turns and outcome, the turns it took, and the tokens it
spent where the runtime's own output carries them.

The Claude Code adapter is given its `claude` process faked at the boundary,
with the stream-json a real run prints; the `acp` adapter talks to a real agent
subprocess over stdio, whose turn ends without any token count.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from agent_build_kit import telemetry
from agent_build_kit.runtimes import AgentRequest, acp, claude_code
from agent_build_kit.runtimes.acp import AcpRuntime
from agent_build_kit.runtimes.claude_code import ClaudeCodeRuntime
from tests.otlp import Collector, enabled
from tests.runtimes.acp_agent import use_agent
from tests.runtimes.claude_cli import MODEL, FakeClaude, failed_build, finished_build


@pytest.fixture
def exported() -> Iterator[Collector]:
    with enabled() as collector:
        assert telemetry.init() is True
        yield collector


def request(cwd: Path, model: str | None = None) -> AgentRequest:
    return AgentRequest(
        prompt="SENTINEL-prompt: add the marker", role="implement", cwd=cwd, model=model
    )


def test_a_claude_code_run_is_an_agent_span_with_its_runtime_model_role_turns_and_outcome(
    tmp_path: Path, exported: Collector
) -> None:
    fake = FakeClaude(stdout=finished_build(tmp_path, "SENTINEL-answer"))

    ClaudeCodeRuntime(execute=fake).run(request(tmp_path, MODEL))
    telemetry.shutdown()

    (span,) = [span for span in exported.spans() if span.name == "agent"]
    assert span.attributes["runtime"] == claude_code.RUNTIME.name
    assert span.attributes["model"] == MODEL
    assert span.attributes["role"] == "implement"
    assert span.attributes["turns"] == 3
    assert span.attributes["outcome"] == "ok"
    assert not [text for text in span.texts() if "SENTINEL" in text], "no prompt, no answer"


def test_a_claude_code_run_that_fails_says_so_without_saying_why(
    tmp_path: Path, exported: Collector
) -> None:
    fake = FakeClaude(stdout=failed_build(tmp_path, "SENTINEL-error: the build broke"))

    ClaudeCodeRuntime(execute=fake).run(request(tmp_path, MODEL))
    telemetry.shutdown()

    (span,) = [span for span in exported.spans() if span.name == "agent"]
    assert span.attributes["outcome"] == "failed"
    assert not [text for text in span.texts() if "SENTINEL" in text]


def test_turns_and_the_tokens_a_claude_code_run_reports_are_recorded_by_role_and_model(
    tmp_path: Path, exported: Collector
) -> None:
    fake = FakeClaude(stdout=finished_build(tmp_path, "done"))

    ClaudeCodeRuntime(execute=fake).run(request(tmp_path, MODEL))
    telemetry.shutdown()

    (turns,) = exported.metric("abk.agent.turns")
    assert turns.attributes == {"role": "implement", "model": MODEL}
    assert (turns.count, turns.value) == (1, 3)
    tokens = {point.attributes["kind"]: point for point in exported.metric("abk.agent.tokens")}
    assert set(tokens) == {"input", "output", "cache"}
    assert tokens["input"].value == 4
    assert tokens["output"].value == 212
    for point in tokens.values():
        assert {k: v for k, v in point.attributes.items() if k != "kind"} == {
            "role": "implement",
            "model": MODEL,
        }


def test_a_runtime_without_token_counts_records_its_turns_and_no_token_series(
    tmp_path: Path, exported: Collector
) -> None:
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    use_agent(tmp_path / "agent.jsonl")

    result = AcpRuntime().run(request(worktree))
    telemetry.shutdown()

    assert result.ok is True
    (span,) = [span for span in exported.spans() if span.name == "agent"]
    assert span.attributes["runtime"] == acp.RUNTIME.name
    assert span.attributes["outcome"] == "ok"
    assert exported.metric("abk.agent.turns")
    assert exported.metric("abk.agent.tokens") == []
