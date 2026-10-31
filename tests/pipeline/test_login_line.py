"""`login_line` copes with what a credentials file or a usage cache may hold, and reads the account
it is asked about (spec: claude-steps-can-renew-their-login).

`abk status` is what a person runs when something is wrong, so a hand-edited file, a clock that
ran ahead or a token time in the wrong unit must not stop it."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from agent_build_kit import claude_account
from agent_build_kit.pipeline import usage_guard
from agent_build_kit.pipeline.usage_guard import login_line


def write_token(account: claude_account.Account, expires_at: object) -> None:
    folder = claude_account.credentials_path(account).parent
    folder.mkdir(parents=True, exist_ok=True)
    claude_account.credentials_path(account).write_text(
        json.dumps({"claudeAiOauth": {"expiresAt": expires_at}})
    )


def write_raw_cache(account: claude_account.Account, text: str) -> None:
    with usage_guard.on_account(account):
        path = usage_guard._cache_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def write_cache(account: claude_account.Account, **fields: object) -> None:
    """The account's usage cache as the kit writes it: carrying the account's key, which a reader
    otherwise takes for another account's file and ignores."""
    write_raw_cache(account, json.dumps({"account": claude_account.account_key(account), **fields}))


@pytest.fixture
def account(tmp_path: Path) -> claude_account.Account:
    return claude_account.Account(label="kit", config_dir=tmp_path / "kit-home")


@pytest.mark.parametrize(
    "expires_at",
    [float("nan"), float("inf"), 1e30, 1_800_000_000, True, "tomorrow", None],
    ids=["nan", "inf", "huge", "in-seconds", "bool", "string", "none"],
)
def test_a_token_time_that_is_not_milliseconds_since_the_epoch_is_unknown(
    account: claude_account.Account, expires_at: object
) -> None:
    write_token(account, expires_at)

    assert "token expiry unknown" in login_line(account)


def test_a_timezone_less_reading_time_does_not_stop_the_line(
    account: claude_account.Account,
) -> None:
    write_token(account, int((datetime.now(UTC) + timedelta(hours=2)).timestamp() * 1000))
    write_cache(account, fetched_at="2026-10-30T10:00:00")

    line = login_line(account)

    assert "last real usage read" in line and "ago" in line


def test_a_reading_time_in_the_future_is_not_a_negative_age(
    account: claude_account.Account,
) -> None:
    write_token(account, int((datetime.now(UTC) + timedelta(hours=2)).timestamp() * 1000))
    ahead = (datetime.now(UTC) + timedelta(minutes=5)).isoformat()
    write_cache(account, fetched_at=ahead)

    assert "last real usage read 0m ago" in login_line(account)


def test_a_cache_that_is_not_an_object_says_no_read_yet(account: claude_account.Account) -> None:
    write_token(account, int((datetime.now(UTC) + timedelta(hours=2)).timestamp() * 1000))

    for text in ("[]", "not json"):
        write_raw_cache(account, text)
        assert "no real usage read yet" in login_line(account)


@pytest.mark.parametrize("fetched", [12, "soon", None], ids=["number", "text", "none"])
def test_a_reading_time_that_is_not_a_time_says_no_read_yet(
    account: claude_account.Account, fetched: object
) -> None:
    write_token(account, int((datetime.now(UTC) + timedelta(hours=2)).timestamp() * 1000))
    write_cache(account, fetched_at=fetched)

    assert "no real usage read yet" in login_line(account)


def test_a_reading_time_the_kit_wrote_is_read_back(account: claude_account.Account) -> None:
    write_token(account, int((datetime.now(UTC) + timedelta(hours=2)).timestamp() * 1000))
    write_cache(account, fetched_at=(datetime.now(UTC) - timedelta(minutes=89)).isoformat())

    assert "last real usage read 89m ago" in login_line(account)


def test_the_line_reads_the_account_it_is_asked_about(
    account: claude_account.Account, tmp_path: Path
) -> None:
    other = claude_account.Account(label="other", config_dir=tmp_path / "other-home")
    write_token(
        account, int((datetime.now(UTC) + timedelta(hours=3, minutes=30)).timestamp() * 1000)
    )
    write_token(other, int((datetime.now(UTC) - timedelta(minutes=45)).timestamp() * 1000))

    assert "(in 3h" in login_line(account)
    assert "token expired 45m ago" in login_line(other)


def test_less_than_a_minute_is_said_as_less_than_a_minute(
    account: claude_account.Account,
) -> None:
    write_token(account, int((datetime.now(UTC) + timedelta(seconds=20)).timestamp() * 1000))

    assert "(in <1m)" in login_line(account)
