"""The agent an `acp` run spawns starts with the environment the request names
(spec: gateway-usage-attribution, the first task): where a per-run gateway key
reaches an agent that reads its key from its environment.

The agent is the real subprocess of `acp_agent.py`, which records the
environment it started with.
"""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.pipeline.gateway_usage import KEY_ENV
from agent_build_kit.runtimes import AgentRequest
from agent_build_kit.runtimes.acp import AcpRuntime
from tests.runtimes.acp_agent import ENVIRONMENT, requests, use_agent


def started_with(record: Path) -> dict[str, str | None]:
    (seen,) = requests(record, ENVIRONMENT)
    return seen


def run(tmp_path: Path, env: dict[str, str] | None = None) -> Path:
    record = tmp_path / "record.jsonl"
    use_agent(record)
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    result = AcpRuntime().run(
        AgentRequest(prompt="Implement group 1.", role="implement", cwd=worktree, env=env or {})
    )
    assert result.ok, result.error
    return record


def test_the_agent_starts_with_the_key_the_request_carries(tmp_path: Path) -> None:
    record = run(tmp_path, {KEY_ENV: "sk-run-1"})

    assert started_with(record) == {KEY_ENV: "sk-run-1"}
