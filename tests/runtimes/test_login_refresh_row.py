"""The login refresh is in the ledger: one `login_refresh` row per call, no tokens or cost because
its output is discarded, a duration, and an outcome from the exit status (spec: usage-accounting,
every agent call writes exactly one row)."""

from __future__ import annotations

import subprocess

import pytest

from agent_build_kit.installation import Installation
from agent_build_kit.runtimes.claude_code import refresh_login
from tests.call_rows import agent_rows


def exiting(code: int):
    def run(argv, **kwargs) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(argv, code, "", "")

    return run


def test_a_refresh_writes_one_login_refresh_row_with_no_figures(workspace: Installation) -> None:
    refresh_login(run=exiting(0))

    (row,) = agent_rows(workspace)
    assert (row["node"], row["unit"], row["role"], row["model"]) == (
        "login_refresh",
        "",
        "generic",
        "haiku",
    )
    assert row["usage_source"] == "none"
    assert row["cost"] is None
    assert row["input_tokens"] is None
    assert row["output_tokens"] is None
    assert isinstance(row["duration_ms"], int)
    assert row["outcome"] == "ok"


@pytest.mark.parametrize(("code", "outcome"), [(0, "ok"), (1, "failed")])
def test_the_outcome_follows_the_exit_status(
    workspace: Installation, code: int, outcome: str
) -> None:
    refresh_login(run=exiting(code))

    assert [row["outcome"] for row in agent_rows(workspace)] == [outcome]
