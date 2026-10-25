"""The stale fallback is the account's `.claude.json`, with the fresh block turned off.

With `usage_claude_cache_minutes: 0` the fresh block is not read, yet `current_usage` and
`held_usage` still fall back to the account's file when nothing else can be read, and the runtime's
usage status over the real readers is the account's reading; the default account's file is never
opened (spec: claude-account, usage-pause).
"""

from datetime import timedelta

import pytest

from agent_build_kit.claude_account import account_key
from agent_build_kit.pipeline import usage_guard
from agent_build_kit.pipeline.usage_guard import current_usage, held_usage
from agent_build_kit.runtimes import claude_code
from agent_build_kit.runtimes.claude_code import ClaudeCodeRuntime
from tests.usage_host import Host, configure, editor_block, pause_at, payload

MINUTE = timedelta(minutes=1)
ACCOUNT_SESSION = 33
DEFAULT_SESSION = 77


@pytest.fixture(autouse=True)
def block_off(host: Host, account_kind: str) -> None:
    configure(usage_claude_cache_minutes=0, **pause_at(92))
    host.use_account(
        block=editor_block(6 * MINUTE, session=ACCOUNT_SESSION, resets_in=timedelta(hours=2))
    )
    host.keep_editor_reading(6 * MINUTE, session=DEFAULT_SESSION)
    host.refuse_default_state_file()


def test_the_held_reading_falls_back_to_the_accounts_file(host: Host) -> None:
    reading = held_usage(host.account)

    assert reading is not None
    assert (reading.source, reading.session_pct) == ("claude.json", ACCOUNT_SESSION)


def test_the_fresh_block_stays_off_and_does_not_replace_the_guards_own_reading(
    host: Host,
) -> None:
    # The kept reading is the account's, so it records the account.
    host.keep_reading(40 * MINUTE, {**payload(session=50.0), "account": account_key(host.account)})

    reading = held_usage(host.account)

    assert reading is not None
    assert (reading.source, reading.session_pct) == ("cache", 50)
    assert host.asked == 0
    # With the account's block as the only reading left it is the fallback.
    host.cache.unlink()
    fallback = held_usage(host.account)
    assert fallback is not None and fallback.source == "claude.json"


def test_the_current_reading_falls_back_to_the_accounts_file_when_the_endpoint_fails(
    host: Host,
) -> None:
    reading = current_usage(host.account)

    assert reading is not None
    assert (reading.source, reading.session_pct) == ("claude.json", ACCOUNT_SESSION)


def test_the_runtime_usage_status_over_the_real_readers_is_the_accounts(
    host: Host, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(claude_code, "read_live_usage", usage_guard.read_live_usage)
    monkeypatch.setattr(claude_code, "read_cached_usage", usage_guard.read_cached_usage)

    status = ClaudeCodeRuntime().get_usage_status()

    assert status is not None
    assert (status.source, status.session_pct) == ("claude.json", ACCOUNT_SESSION)
