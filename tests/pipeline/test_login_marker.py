"""The marker for a rejected login is kept by the handler of the rejection (spec: login-pause).

It carries the credentials' current `expiresAt`, is the entry the usage guard already reads, and is
gone once the credentials carry a different `expiresAt`.
"""

from __future__ import annotations

from agent_build_kit.claude_account import Account
from agent_build_kit.pipeline import usage_guard
from tests.usage_host import HOUR_MS, Host, ms_from_now, write_credentials


def _personal(host: Host) -> Account:
    return Account(label="personal", config_dir=host.home / "second")


def test_the_handler_keeps_the_login_as_rejected_for_the_accounts_credentials(
    host: Host,
) -> None:
    personal = _personal(host)
    write_credentials(host.home / "second", "token", ms_from_now(HOUR_MS))

    usage_guard.record_login_rejected(personal)

    note = usage_guard.rejected_login_note(personal)
    assert note is not None
    assert "personal" in note


def test_another_accounts_login_is_not_marked(host: Host) -> None:
    personal = _personal(host)
    write_credentials(host.home / "second", "token", ms_from_now(HOUR_MS))
    write_credentials(host.home / ".claude", "token", ms_from_now(HOUR_MS))

    usage_guard.record_login_rejected(personal)

    assert usage_guard.rejected_login_note(Account.default()) is None


def test_a_renewed_login_clears_the_marker(host: Host) -> None:
    personal = _personal(host)
    write_credentials(host.home / "second", "old-token", ms_from_now(HOUR_MS))
    usage_guard.record_login_rejected(personal)
    assert usage_guard.rejected_login_note(personal) is not None

    write_credentials(host.home / "second", "new-token", ms_from_now(2 * HOUR_MS))

    assert usage_guard.rejected_login_note(personal) is None
