"""The token-spend question is declared by the real runtimes, not only by a test fake, and
`abk init` asks it of the protocol runtime before the check runs."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.cli import init as init_cmd
from agent_build_kit.cli import main
from agent_build_kit.runtimes import PolicyReport
from agent_build_kit.runtimes.acp import AcpRuntime
from agent_build_kit.runtimes.claude_code import ClaudeCodeRuntime
from tests.cli.policy_step_fakes import Operator, configured, recorded
from tests.cli.test_init import app, init_args, stubs  # noqa: F401 — fixtures


class CheckedAcp(AcpRuntime):
    """The real protocol runtime, its check stubbed: it records that it ran."""

    def __init__(self, log: list[str]) -> None:
        super().__init__()
        self.log = log

    def check_policy(self, cwd: Path) -> PolicyReport:
        self.log.append("check")
        return PolicyReport(ok=True)


def test_the_runtimes_declare_whether_their_check_prompts_the_agent() -> None:
    assert AcpRuntime.policy_check_prompts_agent is True
    assert ClaudeCodeRuntime.policy_check_prompts_agent is False


def test_init_asks_before_the_protocol_runtime_s_check_and_a_refusal_runs_none(
    tmp_path: Path,
    app: Path,  # noqa: F811 — fixture
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    events: list[str] = []
    runtime = CheckedAcp(events)
    planning = configured(tmp_path, app, monkeypatch, runtime, command=["agent-bin", "acp"])
    operator = Operator(capfd, "n", log=events)
    monkeypatch.setattr(init_cmd, "ask", operator)

    main(init_args(planning, app))

    assert events == ["ask"]
    assert "token" in operator.screens[0].lower()
    assert recorded(planning, runtime.name)["policy"] == "unchecked"


def test_init_runs_the_protocol_runtime_s_check_only_after_the_question_is_answered_yes(
    tmp_path: Path,
    app: Path,  # noqa: F811 — fixture
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    events: list[str] = []
    runtime = CheckedAcp(events)
    planning = configured(tmp_path, app, monkeypatch, runtime, command=["agent-bin", "acp"])
    monkeypatch.setattr(init_cmd, "ask", Operator(capfd, "y", log=events))

    assert main(["init", str(planning), "--policy-only"]) == 0

    assert events == ["ask", "check"]
