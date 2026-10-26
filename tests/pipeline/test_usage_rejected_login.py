"""A login rejected after a refresh is named in the start decision (spec: login-refresh).

After one refresh attempt that leaves the token unchanged, a second 401 is a rejected login,
not unknown usage: the decision's detail says so and gives the command to sign in again. Only
the endpoint, the home directory and the `claude` process are faked.
"""

from __future__ import annotations

import logging
import urllib.error

import pytest

from agent_build_kit.claude_account import Account
from agent_build_kit.pipeline import usage_guard
from tests.usage_host import (
    HOUR_MS,
    Host,
    ms_from_now,
    payload,
    reject_login,
    rejection,
    unauthorized,
    write_credentials,
)


def decision_reason(account: Account) -> str:
    with usage_guard.on_account(account):
        return usage_guard.may_start_unit(None).reason


def test_a_labelled_accounts_decision_names_the_rejected_login_and_the_command(
    host: Host,
) -> None:
    personal = Account(label="personal", config_dir=host.home / "second")

    reject_login(host, personal)

    assert rejection(personal) in decision_reason(personal)


def test_the_default_accounts_decision_gives_the_command_without_a_directory(host: Host) -> None:
    default = Account.default()

    reject_login(host, default)

    reason = decision_reason(default)
    assert rejection(default) in reason
    assert "CLAUDE_CONFIG_DIR" not in reason


def test_a_good_reading_after_the_sign_in_ends_the_rejection(host: Host) -> None:
    directory = host.home / "second"
    personal = Account(label="personal", config_dir=directory)
    reject_login(host, personal)
    assert rejection(personal) in decision_reason(personal)

    write_credentials(directory, "new-token", ms_from_now(HOUR_MS))
    host.answers = [payload()]
    with usage_guard.on_account(personal):
        assert usage_guard.read_live_usage() is not None

    assert "rejected" not in decision_reason(personal)


def test_a_second_unchanged_token_read_logs_nothing_new_and_is_still_rejected(
    host: Host, caplog: pytest.LogCaptureFixture
) -> None:
    personal = Account(label="personal", config_dir=host.home / "second")

    with caplog.at_level(logging.WARNING):
        reject_login(host, personal)
        reject_login(host, personal)

    unchanged = [m for m in caplog.messages if "left the saved token as it was" in m]
    assert len(unchanged) == 1
    assert rejection(personal) in decision_reason(personal)


def test_a_new_sign_in_ends_the_rejection_without_a_live_read(host: Host) -> None:
    directory = host.home / "second"
    personal = Account(label="personal", config_dir=directory)
    reject_login(host, personal)
    assert usage_guard.rejected_login_note(personal) is not None

    write_credentials(directory, "new-token", ms_from_now(HOUR_MS))

    assert usage_guard.rejected_login_note(personal) is None
    assert "rejected" not in decision_reason(personal)


def test_a_refreshed_token_that_is_still_refused_is_a_rejected_login(host: Host) -> None:
    directory = host.home / "second"
    personal = Account(label="personal", config_dir=directory)
    host.monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    write_credentials(directory, "old-token", ms_from_now(-HOUR_MS))
    host.answers = [unauthorized(), unauthorized()]

    def refresh(_account: Account) -> None:
        write_credentials(directory, "new-token", ms_from_now(HOUR_MS))

    with usage_guard.on_account(personal):
        assert usage_guard.read_live_usage(refresh=refresh) is None

    assert rejection(personal) in decision_reason(personal)


def test_a_refusal_after_a_plain_network_retry_is_not_a_rejected_login(host: Host) -> None:
    directory = host.home / "second"
    personal = Account(label="personal", config_dir=directory)
    host.monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    write_credentials(directory, "token", ms_from_now(HOUR_MS))
    host.answers = [urllib.error.URLError("unreachable"), unauthorized()]

    with usage_guard.on_account(personal):
        assert usage_guard.read_live_usage() is None

    assert usage_guard.rejected_login_note(personal) is None
    assert "rejected" not in decision_reason(personal)
