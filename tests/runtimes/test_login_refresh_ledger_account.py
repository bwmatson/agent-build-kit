"""A `login_refresh` ledger row names the account the refresh was made for (spec:
claude-steps-can-renew-their-login).

Nine of the fourteen rows written between 2026-10-16 and 2026-10-30 could not be matched to an
account, because the row recorded none, so which account's token the refresh had renewed was a
guess from the times of the usage reads around it."""

from __future__ import annotations

import subprocess
from pathlib import Path

from agent_build_kit import claude_account
from agent_build_kit.installation import Installation
from agent_build_kit.runtimes.claude_code import refresh_login
from tests.call_rows import agent_rows


def succeeding(argv, **kwargs) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(argv, 0, "", "")


def test_a_refresh_of_an_account_with_its_own_folder_names_it(
    workspace: Installation, tmp_path: Path
) -> None:
    account = claude_account.Account(label="kit", config_dir=tmp_path / "kit-home")

    refresh_login(account, run=succeeding)

    (row,) = agent_rows(workspace)
    assert row["node"] == "login_refresh"
    assert row["account"] == claude_account.account_key(account)
    assert row["account"] is not None


def test_a_refresh_of_the_default_account_carries_no_account_key(workspace: Installation) -> None:
    refresh_login(run=succeeding)

    (row,) = agent_rows(workspace)
    assert row["node"] == "login_refresh"
    assert row["account"] is None


def test_two_refreshes_of_two_accounts_are_told_apart(
    workspace: Installation, tmp_path: Path
) -> None:
    kit = claude_account.Account(label="kit", config_dir=tmp_path / "kit-home")

    refresh_login(run=succeeding)
    refresh_login(kit, run=succeeding)

    assert [row["account"] for row in agent_rows(workspace)] == [
        None,
        claude_account.account_key(kit),
    ]
