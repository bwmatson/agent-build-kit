"""Claude Code's own cache is read from the account's `.claude.json`, never the default account's.

With an account set, the fresh block in `decide_start`, `held_usage` and `refreshed_usage` and
`read_cached_usage()` itself use `<dir>/.claude.json`; the default file is not opened, which these
tests enforce by making opening it fail (spec: claude-account). With no setting the default
file's block is used as before: each case ends by showing that, so the difference is the setting.
"""

from datetime import timedelta

import pytest

from agent_build_kit.pipeline import usage_guard
from agent_build_kit.pipeline.usage_guard import (
    decide_start,
    held_usage,
    read_cached_usage,
    refreshed_usage,
)
from tests.usage_host import Host, configure, editor_block, pause_at, payload

MINUTE = timedelta(minutes=1)
LABEL = "(claude.json, 6m old)"
ACCOUNT_SESSION = 33
DEFAULT_SESSION = 77


@pytest.fixture(autouse=True)
def ninety_two(host: Host) -> None:
    configure(**pause_at(92))


def account_block(age: timedelta = 6 * MINUTE) -> dict:
    return editor_block(age, session=ACCOUNT_SESSION, resets_in=timedelta(hours=2))


def old_guard_reading(host: Host) -> None:
    """The guard's own reading, past the cache time and too close to the threshold to settle."""
    host.keep_reading(40 * MINUTE, payload(session=90.0, session_resets_in=timedelta(hours=3)))


def default_block_unreadable(host: Host) -> None:
    host.keep_editor_reading(6 * MINUTE, session=DEFAULT_SESSION)
    host.refuse_default_state_file()


def test_a_start_is_decided_from_the_accounts_block(host: Host) -> None:
    host.use_account(block=account_block())
    default_block_unreadable(host)
    old_guard_reading(host)

    decision = decide_start()

    assert decision.may_start
    assert decision.reason.endswith(LABEL), decision.reason
    assert host.asked == 0


def test_the_held_and_refreshed_readings_are_the_accounts_block(host: Host) -> None:
    host.use_account(block=account_block())
    default_block_unreadable(host)
    old_guard_reading(host)

    held = held_usage()
    refreshed = refreshed_usage()

    assert held is not None and refreshed is not None
    assert (held.source, held.session_pct) == ("claude.json", ACCOUNT_SESSION)
    assert (refreshed.source, refreshed.session_pct) == ("claude.json", ACCOUNT_SESSION)
    assert host.asked == 0


def test_the_cached_reading_is_the_accounts_and_with_no_account_the_default_files(
    host: Host,
) -> None:
    host.keep_editor_reading(6 * MINUTE, session=DEFAULT_SESSION)
    default = read_cached_usage()
    assert default is not None
    assert default.session_pct == DEFAULT_SESSION

    host.use_account(block=account_block())
    host.refuse_default_state_file()
    reading = read_cached_usage()

    assert reading is not None
    assert (reading.source, reading.session_pct) == ("claude.json", ACCOUNT_SESSION)


def test_an_account_with_no_block_has_no_reading_whatever_the_default_file_holds(
    host: Host,
) -> None:
    host.use_account()
    default_block_unreadable(host)

    assert read_cached_usage() is None
    assert held_usage() is None


def test_the_unknown_reason_names_the_file_read_not_the_default_one(host: Host) -> None:
    account = host.use_account()
    host.refuse_default_state_file()

    decision = decide_start()

    assert not decision.may_start
    assert str(account / ".claude.json") in decision.reason
    assert str(usage_guard.DEFAULT_ANCHOR_PATH) not in decision.reason
