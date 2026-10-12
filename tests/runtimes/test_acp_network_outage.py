"""An `acp` run whose failed result names a name that could not be resolved raises.

The agent here answers its prompt with an error naming the unresolved host. A failed
result with no such words stays a failed result.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.runtimes import AgentRequest, NetworkUnavailable, ToolPolicy
from agent_build_kit.runtimes.acp import AcpRuntime
from tests.runtimes.acp_agent import use_agent


def _request(worktree: Path, specs: Path) -> AgentRequest:
    return AgentRequest(
        prompt="Implement group 1 of add-marker.",
        role="implement",
        cwd=worktree,
        add_dirs=(specs,),
        policy=ToolPolicy(specs_dir=specs),
    )


def test_a_failed_result_with_a_strong_sign_raises_and_one_without_stays_a_result(
    tmp_path: Path,
) -> None:
    worktree = tmp_path / "worktree"
    specs = tmp_path / "specs"
    worktree.mkdir()
    specs.mkdir()
    use_agent(tmp_path / "dns.jsonl", fail="dns")

    with pytest.raises(NetworkUnavailable, match="EAI_AGAIN") as caught:
        AcpRuntime().run(_request(worktree, specs))

    assert caught.value.strength == "strong"

    use_agent(tmp_path / "plain.jsonl", fail="error")

    result = AcpRuntime().run(_request(worktree, specs))

    assert result.ok is False
