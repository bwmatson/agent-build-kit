"""The default account is a value: `Account.default()` (spec: claude-account).

No label and no directory; the environment's directory is still resolved lazily, at the time a
path is asked for, so the rules of the setting are unchanged. `None` at a public entry point means
the default account and gives what it gives.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit import claude_account
from agent_build_kit.claude_account import Account
from agent_build_kit.config import WorkspaceConfig
from agent_build_kit.settings import settings


def test_the_default_account_has_no_label_and_no_directory() -> None:
    account = Account.default()

    assert account.label is None
    assert account.config_dir is None
    assert claude_account.is_default(account)


def test_its_directory_is_resolved_when_asked_not_when_made(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    account = Account.default()
    assert claude_account.home(account) == tmp_path / "home" / ".claude"

    monkeypatch.setattr(settings, "claude_home", tmp_path / "configured")

    assert claude_account.home(account) == tmp_path / "configured"
    assert claude_account.credentials_path(account) == tmp_path / "configured" / ".credentials.json"
    assert claude_account.state_file(account) == tmp_path / "configured" / ".claude.json"
    assert claude_account.environment_entry(account) == {
        claude_account.VARIABLE: str(tmp_path / "configured")
    }


@pytest.mark.parametrize("configured", [False, True])
def test_none_gives_what_the_default_account_gives(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, configured: bool
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setattr(settings, "claude_home", tmp_path / "configured" if configured else None)
    default = Account.default()

    assert claude_account.home(None) == claude_account.home(default)
    assert claude_account.credentials_path(None) == claude_account.credentials_path(default)
    assert claude_account.state_file(None) == claude_account.state_file(default)
    assert claude_account.skills_dir(None) == claude_account.skills_dir(default)
    assert claude_account.environment_entry(None) == claude_account.environment_entry(default)
    assert claude_account.account_key(None) == claude_account.account_key(default)


def test_the_default_accounts_files_keep_their_unlabelled_names(tmp_path: Path) -> None:
    path = tmp_path / "usage-cache.json"

    assert claude_account.file_for(path, Account.default()) == path
    assert claude_account.file_for(path, None) == path


def test_a_labelled_accounts_files_are_named_by_its_label(tmp_path: Path) -> None:
    path = tmp_path / "usage-cache.json"
    labelled = Account(label="personal", config_dir=tmp_path / "personal")

    assert claude_account.file_for(path, labelled) == tmp_path / "usage-cache.personal.json"
    assert claude_account.file_for(path, labelled) != claude_account.file_for(
        path, Account.default()
    )


def test_a_labelled_account_with_no_directory_here_is_the_default_account() -> None:
    config = WorkspaceConfig.model_validate(
        {"runtimes": {"claude_code": {"accounts": {"personal": {}}}}}
    )

    assert claude_account.resolve_in(config, "personal") == Account.default()
    assert claude_account.resolve_in(config, None) == Account.default()
