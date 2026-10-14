"""The chat tests that are about the agent process: one that exits before it answers is
reported with its own error text. These keep the stub agent subprocess
(`tests/runtimes/acp_agent.py`); the rest of the chat tests use an in-process fake
(`tests/runtimes/in_process_acp.py`).
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from agent_build_kit.installation import Installation
from tests.chat_serving import turn, unit_worktree
from tests.runtimes.acp_agent import STDERR_LINE, use_agent
from tests.serving import seed_pipeline

# A fake agent's arguments name the session ids it holds, which every server on the machine
# sees, so these cannot run beside each other.
pytestmark = pytest.mark.serial


@pytest.fixture
def pipeline(inst: Installation) -> Installation:
    seed_pipeline(inst)
    unit_worktree(inst, "feature/2")
    return inst


def test_an_agent_that_exits_before_answering_is_reported_with_its_own_error(
    pipeline: Installation, tmp_path: Path, api: httpx.Client
) -> None:
    use_agent(tmp_path / "agent.jsonl", fail="exit")

    events = turn(
        api,
        "/api/sessions",
        {
            "tab": "t1",
            "runtime": "acp",
            "model": "swift-1",
            "unit": "feature/2",
            "prompt": "Look around.",
        },
    )

    [error] = [e for e in events if e["type"] == "RUN_ERROR"]
    assert STDERR_LINE in error["message"], "the agent's own words, not a timeout"
