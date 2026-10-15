"""`abk doctor` reports the Claude Code account and whether it is logged in."""

from __future__ import annotations

import shlex
from pathlib import Path

import pytest

from agent_build_kit.cli.doctor import run_doctor
from tests.account_settings import Configure
from tests.cli.claude_auth_fakes import VARIABLE, FakeClaude, account_lines, in_planning_env, said
from tests.cli.test_doctor import (  # noqa: F401 — fixture
    select_runtime,
    workspace,
)
from tests.factories import which_all


def account_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "second"
    directory.mkdir()
    return directory


@pytest.mark.parametrize(
    ("process", "dotenv", "name", "place"),
    [
        ({}, {"ABK_CLAUDE_HOME": "{dir}"}, "ABK_CLAUDE_HOME", ".env"),
        ({}, {"CLAUDE_CONFIG_DIR": "{dir}"}, "CLAUDE_CONFIG_DIR", ".env"),
        ({"ABK_CLAUDE_HOME": "{dir}"}, {}, "ABK_CLAUDE_HOME", "process"),
        ({"CLAUDE_CONFIG_DIR": "{dir}"}, {}, "CLAUDE_CONFIG_DIR", "process"),
    ],
)
def test_a_logged_in_account_prints_its_directory_source_and_login(
    workspace: Path,  # noqa: F811 — fixture
    tmp_path: Path,
    configure: Configure,
    process: dict[str, str],
    dotenv: dict[str, str],
    name: str,
    place: str,
) -> None:
    directory = account_dir(tmp_path)
    in_planning_env(
        workspace,
        configure,
        process={k: v.format(dir=directory) for k, v in process.items()},
        dotenv={k: v.format(dir=directory) for k, v in dotenv.items()},
    )
    run = FakeClaude()

    checks = account_lines(workspace, run)

    text = said(checks)
    assert checks and all(check.status in ("ok", "info") for check in checks)
    assert str(directory) in text and name in text and place in text
    assert "exists" in text and "logged in" in text
    assert "not logged in" not in text


def test_the_login_question_is_asked_with_the_accounts_variable(
    workspace: Path,  # noqa: F811 — fixture
    tmp_path: Path,
    configure: Configure,
) -> None:
    directory = account_dir(tmp_path)
    in_planning_env(workspace, configure, dotenv={"ABK_CLAUDE_HOME": str(directory)})
    run = FakeClaude()

    account_lines(workspace, run)

    ((argv, env),) = run.asked
    assert argv[0] == "claude"
    assert env is not None and env[VARIABLE] == str(directory)


def test_a_logged_out_account_fails_with_the_exact_login_command(
    workspace: Path,  # noqa: F811 — fixture
    tmp_path: Path,
    configure: Configure,
) -> None:
    directory = account_dir(tmp_path)
    in_planning_env(workspace, configure, dotenv={"ABK_CLAUDE_HOME": str(directory)})

    checks = account_lines(workspace, FakeClaude(status=1, logged_in=False))

    assert [c.status for c in checks if c.status == "FAIL"]
    assert f"{VARIABLE}={directory} claude auth login" in said(checks)


def test_the_login_command_uses_the_configured_claude_command(
    workspace: Path,  # noqa: F811 — fixture
    tmp_path: Path,
    configure: Configure,
) -> None:
    directory = account_dir(tmp_path)
    in_planning_env(workspace, configure, dotenv={"ABK_CLAUDE_HOME": str(directory)})
    select_runtime(workspace, "claude_code", "    command: [claude-wrapper, --flag]\n")

    checks = account_lines(workspace, FakeClaude(status=1, logged_in=False))

    assert f"{VARIABLE}={directory} claude-wrapper --flag auth login" in said(checks)


def test_a_missing_directory_is_a_failure_that_prints_the_login_command_and_asks_nothing(
    workspace: Path,  # noqa: F811 — fixture
    tmp_path: Path,
    configure: Configure,
) -> None:
    directory = tmp_path / "never-made"
    in_planning_env(workspace, configure, dotenv={"ABK_CLAUDE_HOME": str(directory)})
    run = FakeClaude()

    checks = account_lines(workspace, run)

    assert [c for c in checks if c.status == "FAIL"]
    assert "does not exist" in said(checks)
    assert f"{VARIABLE}={directory} claude auth login" in said(checks)
    assert run.asked == []


def test_the_default_account_says_so_and_asks_without_a_variable(
    workspace: Path,  # noqa: F811 — fixture
    configure: Configure,
) -> None:
    in_planning_env(workspace, configure)
    run = FakeClaude()

    checks = account_lines(workspace, run)

    assert "default" in said(checks) and ".claude" in said(checks)
    ((_, env),) = run.asked
    assert env is None or VARIABLE not in env


def test_a_relative_value_is_a_failure_naming_it_and_the_other_checks_still_run(
    workspace: Path,  # noqa: F811 — fixture
    configure: Configure,
) -> None:
    in_planning_env(workspace, configure, dotenv={"ABK_CLAUDE_HOME": "relative/dir"})
    run = FakeClaude()

    checks = run_doctor(workspace / "abk.yaml", run=run, which=which_all)

    (account,) = [c for c in checks if c.name == "runtime account"]
    assert account.status == "FAIL"
    assert "relative/dir" in said([account]) and "ABK_CLAUDE_HOME" in said([account])
    assert run.asked == []
    assert any(c.name == "runtime policy" for c in checks)
    assert any(c.name.startswith("skills") or c.name == "rules" for c in checks)


def test_a_directory_with_a_space_prints_a_login_command_that_splits_back(
    workspace: Path,  # noqa: F811 — fixture
    tmp_path: Path,
    configure: Configure,
) -> None:
    directory = tmp_path / "second account"
    directory.mkdir()
    in_planning_env(workspace, configure, dotenv={"ABK_CLAUDE_HOME": str(directory)})

    checks = account_lines(workspace, FakeClaude(status=1, logged_in=False))

    (check,) = checks
    assert shlex.split(check.fix) == [f"{VARIABLE}={directory}", "claude", "auth", "login"]


def test_a_missing_directory_still_gets_the_token_warning(
    workspace: Path,  # noqa: F811 — fixture
    tmp_path: Path,
    configure: Configure,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    in_planning_env(workspace, configure, dotenv={"ABK_CLAUDE_HOME": str(tmp_path / "never")})
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "sk-ant-oat01-" + "y" * 40)

    checks = account_lines(workspace, FakeClaude())

    assert sorted(c.status for c in checks) == ["FAIL", "warn"]
