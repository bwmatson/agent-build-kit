"""`abk doctor` says that an account's login is rejected after a refresh (spec: login-refresh).

The `claude account` check of a labelled account and the `runtime account` check of the default
one print the same line, with the sign-in command, for the same state.
"""

from __future__ import annotations

from pathlib import Path

from agent_build_kit import claude_account
from agent_build_kit.installation import load_installation
from tests.account_settings import Configure
from tests.cli.claude_auth_fakes import FakeClaude, account_lines, in_planning_env, said
from tests.cli.test_doctor import workspace  # noqa: F401 — fixture
from tests.test_claude_accounts_registry import accounts_checks, name_the_label
from tests.usage_host import Host, reject_login, rejection


def test_a_labelled_accounts_check_names_the_rejected_login_and_its_directory(
    workspace: Path,  # noqa: F811 — fixture
    host: Host,
    configure: Configure,
) -> None:
    directory = host.home / "kit-home"
    directory.mkdir()
    in_planning_env(workspace, configure)
    name_the_label(workspace, directory)
    kit = claude_account.resolve(load_installation(workspace / "abk.yaml"), "kit")
    reject_login(host, kit)

    checks = accounts_checks(workspace, FakeClaude())

    assert rejection(kit) in said(checks)


def test_the_default_accounts_check_prints_the_same_line_without_a_directory(
    workspace: Path,  # noqa: F811 — fixture
    host: Host,
    configure: Configure,
) -> None:
    in_planning_env(workspace, configure)
    default = claude_account.resolve(load_installation(workspace / "abk.yaml"), None)
    reject_login(host, default)

    checks = account_lines(workspace, FakeClaude())

    assert rejection(default) in said(checks)
    assert "CLAUDE_CONFIG_DIR" not in said(checks)
