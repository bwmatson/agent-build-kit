"""`refresh_login` refreshes the login of the account it runs for: the process it starts has the
account's variable over the process's own environment, and none is passed with no account
(spec: claude-account)."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from agent_build_kit.installation import Installation
from agent_build_kit.runtimes.claude_code import refresh_login
from tests.call_rows import agent_rows
from tests.runtimes.account_calls import VARIABLE, use_account


class Recorder:
    def __init__(self) -> None:
        self.kwargs: list[dict] = []

    def __call__(self, argv, **kwargs) -> subprocess.CompletedProcess[str]:
        self.kwargs.append(kwargs)
        return subprocess.CompletedProcess(argv, 0, "", "")


def test_an_account_is_added_over_the_process_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_account(monkeypatch, tmp_path / "account")
    monkeypatch.setenv(VARIABLE, "/elsewhere")
    monkeypatch.setenv("ABK_REFRESH_PROBE", "kept")
    run = Recorder()

    refresh_login(run=run)

    (kwargs,) = run.kwargs
    assert kwargs["env"] == {**os.environ, VARIABLE: str(tmp_path / "account")}
    assert kwargs["env"]["ABK_REFRESH_PROBE"] == "kept"


def test_with_no_account_no_environment_is_passed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_account(monkeypatch, None)
    run = Recorder()
    refresh_login(run=run)
    unset = run.kwargs[0]
    use_account(monkeypatch, tmp_path / "account")
    run = Recorder()
    refresh_login(run=run)

    assert "env" not in unset
    assert "env" in run.kwargs[0], "the same call with an account is told it"


def test_the_ledger_row_is_the_one_written_without_an_account(
    workspace: Installation, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_account(monkeypatch, tmp_path / "account")
    run = Recorder()

    refresh_login(run=run)

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
