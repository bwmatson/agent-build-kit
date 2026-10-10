"""The ACP runtime reports the session's running cost as it came, whether or not the agent
replayed it on resuming, so the recorder can derive the call's own spend from a baseline it
keeps (spec: agent-usage-capture, Every agent call records its own cost and its session's
running total).

The agent is a real subprocess speaking the protocol over stdio (`acp_agent.py`).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.runtimes import AgentRequest
from agent_build_kit.runtimes.acp import AcpRuntime
from tests.runtimes.acp_agent import COST_AMOUNT, use_agent

EARLIER = "sess_Ln3Vt8QaRcXe5mJd"


@pytest.fixture
def worktree(tmp_path: Path) -> Path:
    path = tmp_path / "worktree"
    path.mkdir()
    return path


def _request(worktree: Path, **fields: object) -> AgentRequest:
    return AgentRequest(prompt="Implement group 1.", role="implement", cwd=worktree, **fields)  # pyrefly: ignore


def test_a_new_sessions_amount_is_reported_as_its_cumulative_cost(
    tmp_path: Path, worktree: Path
) -> None:
    use_agent(tmp_path / "agent.jsonl", cost="USD")

    result = AcpRuntime().run(_request(worktree))

    assert result.cumulative_cost_usd == COST_AMOUNT


def test_a_cost_in_another_currency_or_none_leaves_the_cumulative_figure_absent(
    tmp_path: Path, worktree: Path
) -> None:
    use_agent(tmp_path / "usd.jsonl", cost="USD")
    in_dollars = AcpRuntime().run(_request(worktree))
    use_agent(tmp_path / "euro.jsonl", cost="EUR")
    in_euros = AcpRuntime().run(_request(worktree))
    use_agent(tmp_path / "none.jsonl")
    unsaid = AcpRuntime().run(_request(worktree))

    assert in_dollars.cumulative_cost_usd == COST_AMOUNT
    assert in_euros.cumulative_cost_usd is None
    assert unsaid.cumulative_cost_usd is None


def test_a_resumed_sessions_amount_is_its_total_after_the_call(
    tmp_path: Path, worktree: Path
) -> None:
    use_agent(
        tmp_path / "agent.jsonl",
        resume=True,
        list_sessions=True,
        sessions=(EARLIER,),
        cost="USD",
        prior_cost=0.5,
    )

    result = AcpRuntime().run(_request(worktree, resume_session=EARLIER))

    assert result.cumulative_cost_usd == pytest.approx(0.5 + COST_AMOUNT)


def test_a_resumed_call_whose_agent_replayed_no_total_still_reports_the_amount_it_sent(
    tmp_path: Path, worktree: Path
) -> None:
    """The recorder takes the baseline from the ledger, so the runtime must not drop the figure."""
    use_agent(
        tmp_path / "agent.jsonl", resume=True, list_sessions=True, sessions=(EARLIER,), cost="USD"
    )

    result = AcpRuntime().run(_request(worktree, resume_session=EARLIER))

    assert result.cumulative_cost_usd == COST_AMOUNT
