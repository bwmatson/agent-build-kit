"""Every `claude` the Claude Code runtime starts is told the account, over an inherited value
and over the gateway's entries (spec: claude-account)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from agent_build_kit.runtimes import AgentRequest
from agent_build_kit.runtimes.claude_code import ClaudeCodeRuntime, spawn
from tests.runtimes.account_calls import KINDS, VARIABLE, use_account
from tests.runtimes.claude_cli import FakeClaude, finished_build

GATEWAY = {"ANTHROPIC_BASE_URL": "http://gateway.test", "ANTHROPIC_API_KEY": "run-key"}


class EnvironmentClaude(FakeClaude):
    """A `claude` that also records the whole environment a call was given."""

    def __init__(self, stdout: str) -> None:
        super().__init__(stdout=stdout)
        self.environments: list[dict[str, str] | None] = []

    def __call__(self, argv, *, environment=None, **kwargs):
        self.environments.append(environment)
        return super().__call__(argv, **kwargs)


def test_a_build_gets_the_variable_beside_the_gateways_entries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_account(monkeypatch, tmp_path / "account")
    fake = FakeClaude(stdout=finished_build(tmp_path, "Done."))

    ClaudeCodeRuntime(execute=fake).run(
        AgentRequest(prompt="Go.", role="implement", cwd=tmp_path, env=dict(GATEWAY))
    )

    assert fake.envs[0] == {**GATEWAY, VARIABLE: str(tmp_path / "account")}


def test_a_request_with_a_whole_environment_and_no_env_gets_the_variable_added(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_account(monkeypatch, tmp_path / "account")
    fake = EnvironmentClaude(finished_build(tmp_path, "Done."))
    whole = {"PATH": "/bin"}

    ClaudeCodeRuntime(execute=fake).run(
        AgentRequest(prompt="Go.", role="implement", cwd=tmp_path, environment=whole)
    )

    assert fake.envs[0] == {VARIABLE: str(tmp_path / "account")}
    assert fake.environments[0] == whole


def test_the_child_sees_the_setting_once_whatever_the_process_holds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A `.env` value reaches the child although the process has none, one equal to the setting
    is there once, and a different inherited one is replaced."""
    account = tmp_path / "account"
    use_account(monkeypatch, account)
    seen: list[str] = []

    def execute(argv, **kwargs) -> subprocess.CompletedProcess[str]:
        done = spawn(
            ["sh", "-c", f"printf %s \"$(env | grep -c '^{VARIABLE}=')=${VARIABLE}\""], **kwargs
        )
        seen.append(done.stdout)
        return done

    for inherited in (None, str(account), "/elsewhere"):
        monkeypatch.delenv(VARIABLE, raising=False)
        if inherited is not None:
            monkeypatch.setenv(VARIABLE, inherited)
        ClaudeCodeRuntime(execute=execute).run(
            AgentRequest(prompt="Go.", role="implement", cwd=tmp_path)
        )

    assert seen == [f"1={account}"] * 3


@pytest.mark.parametrize("kind", list(KINDS))
def test_every_kind_of_call_carries_the_variable(
    kind: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_account(monkeypatch, tmp_path / "account")

    env = KINDS[kind](tmp_path)

    assert env is not None
    assert env[VARIABLE] == str(tmp_path / "account")
