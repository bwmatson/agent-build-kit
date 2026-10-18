"""The Claude Code spawn runs on the account the request carries (spec: claude-accounts)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit import claude_account
from agent_build_kit.claude_account import Account
from agent_build_kit.runtimes import AgentRequest
from agent_build_kit.runtimes.claude_code import ClaudeCodeRuntime
from tests.runtimes.account_calls import use_account
from tests.runtimes.claude_cli import FakeClaude, finished_build


def spawn_env(tmp_path: Path, account: Account) -> dict[str, str] | None:
    fake = FakeClaude(stdout=finished_build(tmp_path, "Done."))
    ClaudeCodeRuntime(execute=fake).run(
        AgentRequest(prompt="Go.", role="implement", cwd=tmp_path, account=account)
    )
    return fake.envs[0]


def test_the_spawn_environment_names_the_requests_account_directory(tmp_path: Path) -> None:
    directory = tmp_path / "kit-home"

    env = spawn_env(tmp_path, Account(label="kit", config_dir=directory))

    assert env is not None
    assert env[claude_account.VARIABLE] == str(directory)


def test_the_requests_account_wins_over_the_default_account(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    default, directory = tmp_path / "default-home", tmp_path / "kit-home"
    use_account(monkeypatch, default)

    env = spawn_env(tmp_path, Account(label="kit", config_dir=directory))

    assert env is not None
    assert env[claude_account.VARIABLE] == str(directory)
