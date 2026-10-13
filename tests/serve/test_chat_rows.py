"""A chat turn is in the ledger: one `chat` row per turn, carrying the unit the session is attached
to with its change, repository and tier, a resumed turn's own incremental cost, and a blank unit
for a session with none (spec: usage-accounting, every agent call writes exactly one row).

The agent is the `claude` binary faked at its stream-json boundary; the transcript and the
streamed events are those `test_chat_turns.py` pins, so a turn here still ends as it did.
"""

from __future__ import annotations

import httpx
import pytest

from agent_build_kit import runtimes
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.runtimes.claude_code import ClaudeCodeRuntime
from tests.call_rows import agent_rows
from tests.chat_serving import record_session, turn, unit_worktree, use_claude
from tests.runtimes.claude_cli import SESSION, FakeClaude, finished_build
from tests.serving import seed_pipeline

BUILD_SESSION = "0b7e1d52-9c3a-4f8e-b1d6-2a5c7e9f0d51"
REVIEW = "/api/units/feature/2"
FIRST_TOTAL = '"total_cost_usd": 0.4127'


class Growing(FakeClaude):
    """A `claude` whose session total cost grows by 0.5 on each call, as a resumed one's does."""

    def __call__(self, argv, **kwargs):
        grown = 0.4127 + 0.5 * len(self.calls)
        self.stdout = self.original.replace(FIRST_TOTAL, f'"total_cost_usd": {grown}')
        return super().__call__(argv, **kwargs)

    def __init__(self, stdout: str) -> None:
        super().__init__(stdout=stdout)
        self.original = stdout


@pytest.fixture
def pipeline(inst: Installation) -> Installation:
    seed_pipeline(inst)
    record_session(inst, "feature/2", BUILD_SESSION, runtime="claude_code")
    return inst


def test_a_turn_on_a_units_session_writes_one_chat_row_naming_the_unit(
    pipeline: Installation, api: httpx.Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_claude(monkeypatch, finished_build(unit_worktree(pipeline, "feature/2"), "Hello."))

    events = turn(api, f"{REVIEW}/chat", {"tab": "t1", "prompt": "Why this approach?"})

    assert events[-1]["type"] == "RUN_FINISHED"
    stored = UnitStore(pipeline.state_dir / "units.json").get("feature/2")
    (row,) = agent_rows(pipeline)
    assert (row["node"], row["unit"], row["change"], row["repo"], row["tier"], row["role"]) == (
        "chat",
        "feature/2",
        stored.change,
        stored.repo,
        stored.tier,
        "generic",
    )
    assert row["runtime"] == "claude_code"
    assert row["session_id"] == SESSION
    assert row["outcome"] == "ok"
    assert row["cost"]["incremental_usd"] == pytest.approx(0.4127)
    assert row["duration_ms"] == 81234


def test_a_second_turn_s_row_holds_the_turn_s_own_incremental_cost(
    pipeline: Installation, api: httpx.Client
) -> None:
    fake = Growing(finished_build(unit_worktree(pipeline, "feature/2"), "Hello."))
    runtimes.names()
    runtimes._REGISTRY["claude_code"] = ClaudeCodeRuntime(execute=fake)

    turn(api, f"{REVIEW}/chat", {"tab": "t1", "prompt": "First."})
    turn(api, f"{REVIEW}/chat", {"tab": "t1", "prompt": "Second."})

    first, second = agent_rows(pipeline)
    assert [row["node"] for row in (first, second)] == ["chat", "chat"]
    assert first["cost"]["incremental_usd"] == pytest.approx(0.4127)
    assert second["cost"]["incremental_usd"] == pytest.approx(0.5)
    assert second["cost"]["cumulative_usd"] == pytest.approx(0.9127)


def test_a_session_with_no_unit_writes_a_chat_row_with_a_blank_unit(
    pipeline: Installation, api: httpx.Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_claude(monkeypatch, finished_build(pipeline.checkouts["app"], "Hello."))

    turn(
        api,
        "/api/sessions",
        {"tab": "t1", "runtime": "claude_code", "repo": "app", "prompt": "Hi."},
    )

    (row,) = agent_rows(pipeline)
    assert (row["node"], row["unit"]) == ("chat", "")
