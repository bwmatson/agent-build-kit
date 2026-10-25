"""The doctor's login check is one function for every account (spec: claude-account).

The default account at a directory the setting names and a labelled account at the same
directory say the same of the same state, differing only in the name they are called by, and
`auth status` is asked under the account's `CLAUDE_CONFIG_DIR` in both.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from agent_build_kit.claude_account import VARIABLE, Account
from agent_build_kit.runtimes.base import AccountLine
from agent_build_kit.runtimes.claude_code import account_lines
from agent_build_kit.settings import settings

NAME = "the account"


class Status:
    """`claude auth status --json`, answering each call in turn and recording its environment."""

    def __init__(self, *logged_in: bool) -> None:
        self.answers = list(logged_in)
        self.envs: list[dict[str, str] | None] = []

    def __call__(self, argv, **kwargs) -> subprocess.CompletedProcess[str]:
        self.envs.append(kwargs.get("env"))
        return subprocess.CompletedProcess(
            argv, 0, json.dumps({"loggedIn": self.answers.pop(0)}), ""
        )


def accounts_at(directory: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Account]:
    """The default account the setting points at `directory`, and a labelled one naming it."""
    monkeypatch.setattr(settings, "claude_home", directory)
    return {
        "default": Account.default(),
        "labelled": Account(label="personal", config_dir=directory),
    }


@pytest.mark.parametrize("kind", ["default", "labelled"])
def test_asks_auth_status_under_the_accounts_directory(
    kind: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory = tmp_path / "account"
    directory.mkdir()
    run = Status(True)

    account_lines(run, accounts_at(directory, monkeypatch)[kind], NAME)

    (env,) = run.envs
    assert env is not None and env[VARIABLE] == str(directory)


@pytest.mark.parametrize("present", [True, False])
def test_the_same_state_gives_the_same_lines_for_every_account(
    present: bool, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory = tmp_path / "account"
    if present:
        directory.mkdir()
    accounts = accounts_at(directory, monkeypatch)
    found: dict[str, list[list[AccountLine]]] = {}

    for kind, account in accounts.items():
        run = Status(True, False)
        found[kind] = [account_lines(run, account, NAME), account_lines(run, account, NAME)]

    assert found["default"] == found["labelled"]
    first, second = found["default"]
    if present:
        assert [(each.status, each.detail) for each in first] == [
            ("ok", f"{NAME} exists, logged in")
        ]
        assert [(each.status, each.detail) for each in second] == [
            ("FAIL", f"{NAME} exists, not logged in")
        ]
        assert second[0].fix is not None and str(directory) in second[0].fix
    else:
        assert [(each.status, each.detail) for each in first] == [
            ("FAIL", f"{NAME} does not exist")
        ]
