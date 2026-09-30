"""`check_policy` under the `acp` adapter: proving, on this machine, that the
agent's forbidden commands are intercepted rather than assuming it.

Which enforcement point applies depends on the agent, so the adapter asks it
to attempt one representative command per forbidden class and watches what
comes back: a class passes when the attempt reaches abk to be refused — as a
terminal request or a permission request — and fails when the agent runs it
without asking. The fake agent (`acp_agent.py --probe`) attempts each command
the prompt names in an inline code span, and never really runs one.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.runtimes.acp import AcpRuntime
from tests.factories import init_repo
from tests.runtimes.acp_agent import requests, use_agent


@pytest.fixture
def planning(tmp_path: Path) -> Path:
    """Where `doctor` and `init` ask from: the planning checkout, which the
    probe must leave as it found it."""
    root = init_repo(tmp_path / "planning")
    (root / "abk.yaml").write_text("repos: {}\n")
    return root


def _files(root: Path) -> set[Path]:
    return {path for path in root.rglob("*") if ".git" not in path.parts}


@pytest.mark.parametrize("attempts", ["terminal", "ask"])
def test_an_agent_that_honours_refusals_has_every_class_enforced(
    tmp_path: Path, planning: Path, attempts: str
) -> None:
    """Both points count: an agent that defers its commands to the client, and
    one that runs its own but asks about each."""
    record = tmp_path / "agent.jsonl"
    use_agent(record, probe=attempts)
    before = _files(planning)

    report = AcpRuntime().check_policy(planning)

    assert report.ok is True, report
    assert report.unenforced == ()
    # The agent was really asked, and the probe worked somewhere of its own.
    assert requests(record, "session/prompt")
    assert requests(record, f"did/{'terminal' if attempts == 'terminal' else 'ask'}")
    assert _files(planning) == before


def test_an_agent_that_runs_a_forbidden_command_anyway_has_that_class_reported(
    tmp_path: Path, planning: Path
) -> None:
    """The agent's own configuration does not flag merging a pull request, so
    it runs the merge without asking: that class, and only that one, is
    reported unenforced — the rest were still refused."""
    record = tmp_path / "agent.jsonl"
    use_agent(record, probe="ask", unasked="gh pr merge")

    report = AcpRuntime().check_policy(planning)

    ran = [entry["command"] for entry in requests(record, "did/run")]
    assert any(command and command.startswith("gh pr merge") for command in ran), ran
    assert report.ok is False
    assert len(report.unenforced) == 1, report
    assert "pull request" in report.unenforced[0]
