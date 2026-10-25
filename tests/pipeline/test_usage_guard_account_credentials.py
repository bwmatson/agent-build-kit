"""The token and its expiry are read from the account's own `.credentials.json`.

For the default account at a directory the setting names and for a labelled account with a
directory of its own alike (`account_kind`), `read_oauth_token` and `token_expired` open
`<dir>/.credentials.json` instead of the default file; `CLAUDE_CODE_OAUTH_TOKEN` is still first
and a path argument still wins; the refresh the guard makes after an expired token is told the
account and the read after it is of the account's file (spec: claude-account). With no directory
set the default file is the one read, so the difference is the account.

Only the endpoint, the home directory and the `claude` process are faked.
"""

import json
import os
from pathlib import Path

import pytest

from agent_build_kit.claude_account import VARIABLE
from agent_build_kit.pipeline import usage_guard
from agent_build_kit.runtimes import claude_code
from agent_build_kit.runtimes.claude_code import refresh_login
from tests.usage_host import HOUR_MS, Host, ms_from_now, payload, unauthorized, write_credentials


def write_default(host: Host, token: str, expires_at_ms: int | None = None) -> None:
    """The default account's credentials, in the file the guard names with no directory set."""
    write_credentials(host.home / ".claude", token, expires_at_ms)


@pytest.fixture
def no_env_token(host: Host, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN")


@pytest.mark.usefixtures("no_env_token")
def test_with_no_directory_set_the_default_files_are_read(host: Host) -> None:
    write_default(host, "default-token", ms_from_now(-HOUR_MS))

    assert usage_guard.read_oauth_token() == "default-token"
    assert usage_guard.token_expired() is True


@pytest.mark.usefixtures("no_env_token", "account_kind")
def test_the_token_is_the_accounts(host: Host) -> None:
    write_default(host, "default-token")
    host.use_account(token="account-token")

    assert usage_guard.read_oauth_token() == "account-token"


@pytest.mark.usefixtures("no_env_token", "account_kind")
def test_the_expiry_is_the_accounts(host: Host) -> None:
    write_default(host, "default-token", ms_from_now(HOUR_MS))
    host.use_account(token="account-token", expires_at_ms=ms_from_now(-HOUR_MS))
    assert usage_guard.token_expired() is True

    write_default(host, "default-token", ms_from_now(-HOUR_MS))
    host.use_account(token="account-token", expires_at_ms=ms_from_now(HOUR_MS))
    assert usage_guard.token_expired() is False


@pytest.mark.usefixtures("account_kind")
def test_the_environment_token_is_still_first(host: Host, monkeypatch: pytest.MonkeyPatch) -> None:
    host.use_account(token="account-token")
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "env-token")
    assert usage_guard.read_oauth_token() == "env-token"

    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN")
    assert usage_guard.read_oauth_token() == "account-token"


@pytest.mark.usefixtures("no_env_token", "account_kind")
def test_a_path_argument_still_wins(host: Host, tmp_path: Path) -> None:
    host.use_account(token="account-token", expires_at_ms=ms_from_now(-HOUR_MS))
    write_credentials(tmp_path, "given-token", ms_from_now(HOUR_MS))
    given = tmp_path / ".credentials.json"

    assert usage_guard.read_oauth_token(given) == "given-token"
    assert usage_guard.token_expired(given) is False
    assert usage_guard.read_oauth_token() == "account-token"
    assert usage_guard.token_expired() is True


@pytest.mark.usefixtures("no_env_token", "account_kind")
def test_after_an_expired_token_the_refresh_is_told_the_account_and_the_second_read_is_its_file(
    host: Host, monkeypatch: pytest.MonkeyPatch
) -> None:
    account = host.use_account(token="old-token", expires_at_ms=ms_from_now(-HOUR_MS))
    write_default(host, "default-token", ms_from_now(HOUR_MS))
    environments: list[dict[str, str] | None] = []

    def claude(argv, **kwargs):
        # What a real `claude` does for the account it is told: it writes a fresh token there.
        environments.append(kwargs.get("env"))
        (account / ".credentials.json").write_text(
            json.dumps(
                {"claudeAiOauth": {"accessToken": "new-token", "expiresAt": ms_from_now(HOUR_MS)}}
            )
        )

    monkeypatch.setattr(
        claude_code, "refresh_login", lambda account=None: refresh_login(account, run=claude)
    )
    sent = host.record_bearers()
    host.answers = [unauthorized(), payload()]

    reading = usage_guard.read_live_usage()

    assert reading is not None
    assert [env[VARIABLE] if env else None for env in environments] == [str(account)]
    assert environments[0] == {**os.environ, VARIABLE: str(account)}
    assert sent == ["Bearer old-token", "Bearer new-token"]


@pytest.mark.usefixtures("account_kind")
def test_a_fresh_account_token_is_not_refreshed(
    host: Host, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The account's expiry decides, not the default file's: a default file past its expiry
    must not start a refresh when the account's token is good."""
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN")
    write_default(host, "default-token", ms_from_now(-HOUR_MS))
    host.use_account(token="account-token", expires_at_ms=ms_from_now(HOUR_MS))
    refreshed: list[bool] = []
    host.answers = [unauthorized()]

    usage_guard.read_live_usage(refresh=lambda account: refreshed.append(True))

    assert refreshed == []
