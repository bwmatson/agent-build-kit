"""Every account goes through one path in the usage guard (spec: claude-account).

The default account and a labelled one with a directory are read by the same code: the
credentials, the expiry and the refresh take the account, and the 401 retry hands it to its hooks
instead of reading the context variable. The guard keeps no constant and no default branch of its
own for the default account's files.
"""

from __future__ import annotations

import pytest

from agent_build_kit.claude_account import Account
from agent_build_kit.pipeline import usage_guard
from tests.usage_host import (
    HOUR_MS,
    Host,
    ms_from_now,
    payload,
    unauthorized,
    write_credentials,
)

DRIFTED = ("CREDENTIALS_PATH", "DEFAULT_ANCHOR_PATH", "_credentials_path", "_state_file")


class Accounts:
    """The default account and a labelled one, each with a directory of its own."""

    def __init__(self, host: Host, kind: str) -> None:
        self.host = host
        self.default_dir = host.home / ".claude"
        self.labelled_dir = host.home / "second"
        self.account = (
            Account.default()
            if kind == "default"
            else Account(label="personal", config_dir=self.labelled_dir)
        )
        self.directory = self.default_dir if kind == "default" else self.labelled_dir

    def write(self, token: str, expires_at_ms: int | None = None) -> None:
        """The account's credentials; the other account's hold a token that must not be read."""
        write_credentials(self.directory, token, expires_at_ms)
        other = self.labelled_dir if self.directory == self.default_dir else self.default_dir
        write_credentials(other, "the-other-accounts-token", ms_from_now(-HOUR_MS))


@pytest.fixture(params=["default", "labelled"])
def accounts(host: Host, request: pytest.FixtureRequest) -> Accounts:
    host.monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN")
    return Accounts(host, request.param)


def test_the_token_is_read_from_the_accounts_credentials(accounts: Accounts) -> None:
    accounts.write("the-token")

    assert usage_guard.read_oauth_token(account=accounts.account) == "the-token"


def test_the_expiry_is_the_accounts(accounts: Accounts) -> None:
    accounts.write("the-token", ms_from_now(-HOUR_MS))
    assert usage_guard.token_expired(account=accounts.account) is True

    accounts.write("the-token", ms_from_now(HOUR_MS))
    assert usage_guard.token_expired(account=accounts.account) is False


def test_the_account_in_force_is_the_one_set_else_the_default(accounts: Accounts) -> None:
    assert usage_guard.account_in_force() == Account.default()

    with usage_guard.on_account(accounts.account):
        assert usage_guard.account_in_force() == accounts.account


def test_the_hooks_of_the_401_retry_are_handed_the_account(host: Host, accounts: Accounts) -> None:
    accounts.write("old-token", ms_from_now(-HOUR_MS))
    expired_for: list[Account] = []
    refreshed_for: list[Account] = []

    def expired(account: Account) -> bool:
        expired_for.append(account)
        return True

    def refresh(account: Account) -> None:
        refreshed_for.append(account)
        write_credentials(accounts.directory, "new-token", ms_from_now(HOUR_MS))

    sent = host.record_bearers()
    host.answers = [unauthorized(), payload()]

    with usage_guard.on_account(accounts.account):
        reading = usage_guard.read_live_usage(expired=expired, refresh=refresh)

    assert reading is not None
    assert expired_for == [accounts.account]
    assert refreshed_for == [accounts.account]
    assert sent == ["Bearer old-token", "Bearer new-token"]


def test_the_hooks_are_handed_the_default_account_when_none_is_set(host: Host) -> None:
    host.monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN")
    accounts = Accounts(host, "default")
    accounts.write("old-token", ms_from_now(-HOUR_MS))
    handed: list[Account] = []
    host.answers = [unauthorized()]

    usage_guard.read_live_usage(
        expired=lambda account: handed.append(account) is None, refresh=lambda account: None
    )

    assert handed == [Account.default()]


@pytest.mark.parametrize("name", DRIFTED)
def test_the_guard_has_no_default_branch_of_its_own(name: str) -> None:
    assert name not in vars(usage_guard)
