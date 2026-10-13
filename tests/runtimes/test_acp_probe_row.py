"""The policy probe is in the ledger: one `policy_probe` row after the probe, written although the
probe drives the agent directly and never reaches a request's `on_result` (spec: usage-accounting,
every agent call writes exactly one row)."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.installation import Installation
from agent_build_kit.runtimes.acp import AcpRuntime
from tests.call_rows import agent_rows
from tests.runtimes.acp_agent import use_agent


def test_a_probe_writes_one_policy_probe_row(
    tmp_path: Path, planning: Path, workspace: Installation
) -> None:
    use_agent(tmp_path / "agent.jsonl", probe="terminal")

    AcpRuntime().check_policy(planning)

    (row,) = agent_rows(workspace)
    assert (row["node"], row["unit"], row["change"], row["repo"], row["role"]) == (
        "policy_probe",
        "",
        "",
        "",
        "generic",
    )
    assert row["runtime"] == "acp"
    assert row["outcome"] == "ok"
