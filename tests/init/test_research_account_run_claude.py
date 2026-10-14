"""An init step given a `run_claude` still runs with an account set: the runtime adds the
account's variable to the call, and the stand-in for the executable, which takes no
environment, is not handed one (spec: claude-account)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.init.research import research
from tests.runtimes.account_calls import use_account


def test_research_with_a_two_argument_run_claude_runs_under_an_account(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_account(monkeypatch, tmp_path / "account")
    calls: list[list[str]] = []

    def run_claude(argv: list[str], *, cwd: Path | None = None) -> str:
        calls.append(argv)
        return "# Rules\n\nSources: none.\n"

    output = research("python", built_in=None, output=tmp_path / "python.md", run_claude=run_claude)

    assert len(calls) == 1
    assert "# Rules" in output.read_text()
