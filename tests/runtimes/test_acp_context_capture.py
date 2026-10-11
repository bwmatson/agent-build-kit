"""The ACP runtime hands its caller how full the context window was, from the `usage_update`s
the agent sends: `used` is the tokens in the context, `size` the window (spec: usage-accounting,
Every agent call records its context window use in tokens).

The agent is a real subprocess speaking the protocol over stdio (`acp_agent.py`).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.runtimes import AgentRequest
from agent_build_kit.runtimes.acp import AcpRuntime
from agent_build_kit.usage import ContextBasis
from tests.runtimes.acp_agent import CONTEXT_SIZE, use_agent

EARLIER = "sess_Ln3Vt8QaRcXe5mJd"
K = 1000


@pytest.fixture
def worktree(tmp_path: Path) -> Path:
    path = tmp_path / "worktree"
    path.mkdir()
    return path


def _request(worktree: Path, **fields: object) -> AgentRequest:
    return AgentRequest(prompt="Implement group 1.", role="implement", cwd=worktree, **fields)  # pyrefly: ignore


def test_a_new_sessions_first_update_is_where_the_step_started_and_its_last_is_where_it_ended(
    tmp_path: Path, worktree: Path
) -> None:
    use_agent(tmp_path / "agent.jsonl", fills=(9 * K, 12 * K, 15 * K))

    result = AcpRuntime().run(_request(worktree))

    context = result.context
    assert context is not None
    assert context.used_start == 9 * K
    assert context.used_end == 15 * K
    assert context.added == 6 * K
    assert context.peak == 15 * K
    assert context.max == CONTEXT_SIZE
    assert context.basis == ContextBasis.REPORTED


def test_a_resumed_session_starts_from_where_the_last_step_ended(
    tmp_path: Path, worktree: Path
) -> None:
    use_agent(
        tmp_path / "agent.jsonl",
        resume=True,
        list_sessions=True,
        sessions=(EARLIER,),
        prior_fill=40 * K,
        fills=(45 * K, 52 * K),
    )

    result = AcpRuntime().run(_request(worktree, resume_session=EARLIER))

    context = result.context
    assert context is not None
    assert context.used_start == 40 * K
    assert context.used_end == 52 * K
    assert context.added == 12 * K


def test_a_fall_in_used_larger_than_the_share_of_the_window_is_one_compaction(
    tmp_path: Path, worktree: Path
) -> None:
    use_agent(tmp_path / "agent.jsonl", fills=(150 * K, 195 * K, 80 * K))

    result = AcpRuntime().run(_request(worktree))

    context = result.context
    assert context is not None
    assert context.compactions == 1
    assert context.added == 0
    assert context.peak == 195 * K
    assert context.used_end == 80 * K


def test_an_agent_that_sends_no_usage_update_leaves_the_context_absent_and_the_run_unaffected(
    tmp_path: Path, worktree: Path
) -> None:
    use_agent(tmp_path / "agent.jsonl")

    result = AcpRuntime().run(_request(worktree))

    assert result.ok
    assert result.context is None


def test_an_update_carrying_only_a_cost_leaves_the_context_absent_and_the_run_unaffected(
    tmp_path: Path, worktree: Path
) -> None:
    use_agent(tmp_path / "agent.jsonl", fills=(None, None))

    result = AcpRuntime().run(_request(worktree))

    assert result.ok
    assert result.context is None


def test_a_cost_only_update_between_real_fills_is_neither_a_fill_nor_a_compaction(
    tmp_path: Path, worktree: Path
) -> None:
    use_agent(tmp_path / "agent.jsonl", fills=(150 * K, None, 170 * K))

    result = AcpRuntime().run(_request(worktree))

    context = result.context
    assert context is not None
    assert context.compactions == 0
    assert context.used_start == 150 * K
    assert context.used_end == 170 * K
    assert context.added == 20 * K
    assert context.max == CONTEXT_SIZE
