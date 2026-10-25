"""`refresh_login` refreshes the login of the account it runs for: the process it starts has the
account's variable over the process's own environment, and none is passed with no directory
(spec: claude-account). Each case runs for the default account at a directory the setting names
and for a labelled account with a directory of its own."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from agent_build_kit.claude_account import VARIABLE, Account
from agent_build_kit.installation import Installation
from agent_build_kit.runtimes.claude_code import refresh_login
from tests.call_rows import agent_rows
from tests.runtimes.account_calls import use_account


class Recorder:
    def __init__(self) -> None:
        self.kwargs: list[dict] = []

    def __call__(self, argv, **kwargs) -> subprocess.CompletedProcess[str]:
        self.kwargs.append(kwargs)
        return subprocess.CompletedProcess(argv, 0, "", "")


@pytest.fixture(params=["default", "labelled"])
def account(
    request: pytest.FixtureRequest, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Account:
    """An account whose directory is `tmp_path / "account"`: the default account through the
    setting, or a labelled one that names it."""
    directory = tmp_path / "account"
    if request.param == "default":
        use_account(monkeypatch, directory)
        return Account.default()
    use_account(monkeypatch, None)
    return Account(label="personal", config_dir=directory)


def test_an_account_is_added_over_the_process_environment(
    account: Account, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(VARIABLE, "/elsewhere")
    monkeypatch.setenv("ABK_REFRESH_PROBE", "kept")
    run = Recorder()

    refresh_login(account, run=run)

    (kwargs,) = run.kwargs
    assert kwargs["env"] == {**os.environ, VARIABLE: str(tmp_path / "account")}
    assert kwargs["env"]["ABK_REFRESH_PROBE"] == "kept"


def test_with_no_directory_no_environment_is_passed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_account(monkeypatch, None)
    run = Recorder()
    refresh_login(Account.default(), run=run)
    unset = run.kwargs[0]
    use_account(monkeypatch, tmp_path / "account")
    run = Recorder()
    refresh_login(Account.default(), run=run)

    assert "env" not in unset
    assert "env" in run.kwargs[0], "the same call with a directory is told it"


@pytest.mark.parametrize("directory", [False, True])
def test_no_account_is_the_default_account(
    directory: bool, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_account(monkeypatch, tmp_path / "account" if directory else None)
    none, default = Recorder(), Recorder()

    refresh_login(None, run=none)
    refresh_login(Account.default(), run=default)

    assert none.kwargs == default.kwargs


def test_the_ledger_row_is_the_one_written_without_an_account(
    account: Account, workspace: Installation
) -> None:
    run = Recorder()

    refresh_login(account, run=run)

    assert "env" in run.kwargs[0]
    (row,) = agent_rows(workspace)
    assert (row["node"], row["unit"], row["role"], row["model"]) == (
        "login_refresh",
        "",
        "generic",
        "haiku",
    )
    assert row["usage_source"] == "none"
    assert row["cost"] is None
    assert row["outcome"] == "ok"
