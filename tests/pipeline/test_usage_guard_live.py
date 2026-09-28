"""Reading usage from the endpoint the /usage panel itself calls.

`GET api.anthropic.com/api/oauth/usage`, with the OAuth token Claude Code
already stores and the `anthropic-beta: oauth-2025-04-20` header, answers with
live window percentages. That removes the staleness problem entirely: no
calibration, no cost ledger, no waiting for an interactive session to refresh
a cache.

It is undocumented, so these tests pin the two things that matter when it
changes: a response we don't recognise reads as unknown (which pauses), and
the cached-file fallback still works.
"""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from agent_build_kit.pipeline import usage_guard
from agent_build_kit.pipeline.usage_guard import (
    UsageReading,
    may_start_unit,
    read_live_usage,
)

LIVE_RESPONSE = {
    "five_hour": {
        "utilization": 14.0,
        "resets_at": "2026-09-24T00:50:00.460447+00:00",
    },
    "seven_day": {
        "utilization": 6.0,
        "resets_at": "2026-09-30T02:00:00.460472+00:00",
    },
    "extra_usage": {
        "is_enabled": True,
        "monthly_limit": 10000,
        "used_credits": 1324.0,
        "spend_limit_reached": False,
    },
}


def fetcher(payload: object, *, record: list | None = None):
    def fetch(url: str, headers: dict[str, str]) -> object:
        if record is not None:
            record.append((url, headers))
        if isinstance(payload, Exception):
            raise payload
        return payload

    return fetch


def test_reads_live_percentages_and_reset_times(tmp_path: Path) -> None:
    reading = read_live_usage(
        token="t", fetch=fetcher(LIVE_RESPONSE), cache_path=tmp_path / "c.json"
    )

    assert reading is not None
    assert reading.session_pct == 14
    assert reading.weekly_pct == 6
    assert reading.source == "live"
    assert reading.resets_at is not None
    assert reading.resets_at.isoformat().startswith("2026-09-24T00:50")


def test_sends_the_beta_header_and_bearer_token(tmp_path: Path) -> None:
    """Without the beta header the endpoint doesn't answer; without the token
    it answers for nobody."""
    calls: list = []

    read_live_usage(
        token="secret", fetch=fetcher(LIVE_RESPONSE, record=calls), cache_path=tmp_path / "c.json"
    )

    _, headers = calls[0]
    assert headers["Authorization"] == "Bearer secret"
    assert headers["anthropic-beta"] == "oauth-2025-04-20"


def test_credits_state_is_carried_through(tmp_path: Path) -> None:
    """The account has credits enabled past the plan limit, so going over
    spends real money. The guard has to be able to see that directly."""
    reading = read_live_usage(
        token="t", fetch=fetcher(LIVE_RESPONSE), cache_path=tmp_path / "c.json"
    )

    assert reading is not None
    assert reading.credits_enabled
    assert reading.credits_used_dollars == pytest.approx(13.24)
    assert not reading.spend_limit_reached


def test_a_second_call_within_the_ttl_does_not_hit_the_endpoint(tmp_path: Path) -> None:
    """A unit-start check runs often; the endpoint is somebody else's service."""
    calls: list = []
    cache = tmp_path / "c.json"

    read_live_usage(token="t", fetch=fetcher(LIVE_RESPONSE, record=calls), cache_path=cache)
    second = read_live_usage(
        token="t", fetch=fetcher(LIVE_RESPONSE, record=calls), cache_path=cache
    )

    assert len(calls) == 1
    assert second is not None
    assert second.session_pct == 14


def test_the_cache_expires(tmp_path: Path) -> None:
    calls: list = []
    cache = tmp_path / "c.json"

    read_live_usage(
        token="t", fetch=fetcher(LIVE_RESPONSE, record=calls), cache_path=cache, ttl=timedelta(0)
    )
    read_live_usage(
        token="t", fetch=fetcher(LIVE_RESPONSE, record=calls), cache_path=cache, ttl=timedelta(0)
    )

    assert len(calls) == 2


def test_a_failed_request_reads_as_unknown_not_as_zero(tmp_path: Path) -> None:
    """Undocumented endpoint: it can change, 401, or vanish. None pauses."""
    reading = read_live_usage(
        token="t", fetch=fetcher(OSError("connection refused")), cache_path=tmp_path / "c.json"
    )

    assert reading is None


@pytest.mark.parametrize(
    "payload",
    [{}, {"five_hour": {}}, {"five_hour": {"utilization": "lots"}}, [], None],
)
def test_an_unrecognized_response_reads_as_unknown(payload: object, tmp_path: Path) -> None:
    assert (
        read_live_usage(token="t", fetch=fetcher(payload), cache_path=tmp_path / "c.json") is None
    )


def test_no_discoverable_token_means_no_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """On a machine where Claude Code has never logged in there is nothing to
    send, and an unauthenticated request would only produce a 401."""
    calls: list = []
    monkeypatch.setattr(usage_guard, "read_oauth_token", lambda *a, **k: None)

    reading = read_live_usage(
        fetch=fetcher(LIVE_RESPONSE, record=calls), cache_path=tmp_path / "c.json"
    )

    assert reading is None
    assert calls == []


def test_an_omitted_token_is_discovered(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Callers shouldn't have to know where Claude Code keeps its token."""
    calls: list = []
    monkeypatch.setattr(usage_guard, "read_oauth_token", lambda *a, **k: "discovered")

    read_live_usage(fetch=fetcher(LIVE_RESPONSE, record=calls), cache_path=tmp_path / "c.json")

    _, headers = calls[0]
    assert headers["Authorization"] == "Bearer discovered"


def test_the_token_is_never_written_to_the_cache(tmp_path: Path) -> None:
    """The cache is a plain file in the repo's runs/ directory."""
    cache = tmp_path / "c.json"

    read_live_usage(token="super-secret", fetch=fetcher(LIVE_RESPONSE), cache_path=cache)

    assert "super-secret" not in cache.read_text()


def live(**overrides) -> UsageReading:
    defaults: dict = {
        "session_pct": 10,
        "weekly_pct": 10,
        "resets_at": datetime.now(UTC) + timedelta(hours=3),
        "observed_at": datetime.now(UTC),
        "source": "live",
        "credits_enabled": True,
        "credits_used_dollars": 13.24,
        "spend_limit_reached": False,
    }
    return UsageReading(**{**defaults, **overrides})


def test_a_live_reading_is_never_treated_as_stale() -> None:
    """Staleness is a property of the cached file, not of a fresh request."""
    decision = may_start_unit(live(observed_at=datetime.now(UTC) - timedelta(hours=9)))

    assert decision.may_start


def test_spending_credits_stops_new_work() -> None:
    """Past the plan limit, work costs money. That is never something to start
    unattended, whatever the percentages say."""
    decision = may_start_unit(live(session_pct=5, spend_limit_reached=True))

    assert not decision.may_start
    assert "credit" in decision.reason.lower()


def test_a_full_window_with_credits_enabled_stops_new_work() -> None:
    """At 100% the next call is paid for out of credits, so the percentage
    itself is the signal — the guard doesn't wait to be told."""
    decision = may_start_unit(live(session_pct=100))

    assert not decision.may_start
    assert "credit" in decision.reason.lower()


def test_credits_never_raise_the_ceiling() -> None:
    """Credits are a backstop, not headroom.

    Having credits available must not let unattended work run past the
    threshold — the whole point of 70% is to leave the rest of the plan window
    for the user, with credits untouched underneath it.
    """
    decision = may_start_unit(live(session_pct=70, credits_enabled=True, credits_used_dollars=0.0))

    assert not decision.may_start
    assert "70%" in decision.reason
    assert "threshold" in decision.reason


def test_the_threshold_is_what_stops_work_not_the_credits_rules() -> None:
    """Between the threshold and 100% the credits rules haven't fired yet, so
    this is the case that proves the percentage is doing the stopping."""
    decision = may_start_unit(live(session_pct=85, weekly_pct=12))

    assert not decision.may_start
    assert "session usage at 85%" in decision.reason
    assert "credit" not in decision.reason.lower()


def test_a_healthy_credit_balance_does_not_unlock_a_full_window() -> None:
    """Plenty of credits left, window full: still stop. The credits exist for
    the user's own work, not for the pipeline to spend unattended."""
    decision = may_start_unit(live(session_pct=100, credits_enabled=True, credits_used_dollars=0.0))

    assert not decision.may_start


def test_the_reason_names_the_source_so_run_logs_are_readable() -> None:
    decision = may_start_unit(live(session_pct=12))

    assert decision.may_start
    assert "live" in decision.reason


def test_cached_file_readings_still_age_out() -> None:
    old = UsageReading(
        session_pct=10,
        weekly_pct=10,
        resets_at=datetime.now(UTC) + timedelta(hours=3),
        observed_at=datetime.now(UTC) - timedelta(hours=4),
        source="claude.json",
        credits_enabled=False,
        credits_used_dollars=0.0,
        spend_limit_reached=False,
    )

    decision = may_start_unit(old)

    assert not decision.may_start
    assert "stale" in decision.reason.lower()


def test_cache_file_round_trips_without_the_endpoint(tmp_path: Path) -> None:
    """A cached response must be readable by the next process, since each
    scheduler tick is a new one."""
    cache = tmp_path / "c.json"
    read_live_usage(token="t", fetch=fetcher(LIVE_RESPONSE), cache_path=cache)

    from_disk = json.loads(cache.read_text())

    assert from_disk["five_hour"]["utilization"] == 14.0
    assert "fetched_at" in from_disk


def test_an_expired_token_is_refreshed_once_and_the_read_retried(tmp_path: Path) -> None:
    """Overnight the token expired and nothing refreshed it: every tick paused
    for want of a usage reading, from the reset until a session was opened."""
    from agent_build_kit.pipeline import usage_guard

    tokens = iter(["old-token", "new-token"])
    seen: list[str] = []

    def fetch(url, headers):
        seen.append(headers["Authorization"])
        if headers["Authorization"].endswith("old-token"):
            raise OSError("401 Unauthorized")
        return LIVE_RESPONSE

    refreshed: list[bool] = []
    original = usage_guard.read_oauth_token
    usage_guard.read_oauth_token = lambda path=None: next(tokens)
    try:
        reading = read_live_usage(
            fetch=fetch,
            cache_path=tmp_path / "cache.json",
            expired=lambda: True,
            refresh=lambda: refreshed.append(True),
        )
    finally:
        usage_guard.read_oauth_token = original

    assert refreshed == [True]
    assert seen == ["Bearer old-token", "Bearer new-token"]
    assert reading is not None


def test_a_token_that_has_not_expired_is_not_refreshed(tmp_path: Path) -> None:
    """Any other failure stays "unknown", which pauses: a refresh is for the
    one state it is known to fix, not a general retry."""

    def fetch(url, headers):
        raise OSError("503")

    refreshed: list[bool] = []
    reading = read_live_usage(
        token=None,
        fetch=fetch,
        cache_path=tmp_path / "cache.json",
        expired=lambda: False,
        refresh=lambda: refreshed.append(True),
    )

    assert reading is None
    assert refreshed == []


def test_no_open_window_is_room_to_work_not_unknown_usage(tmp_path: Path) -> None:
    """Once a five-hour window ends and nothing starts another, the endpoint
    says `resets_at: null`. Read as unknown usage it paused every tick, and a
    paused pipeline never opens a window — it stayed stuck until someone used
    Claude by hand."""
    from agent_build_kit.pipeline.usage_guard import may_start_unit

    idle = {**LIVE_RESPONSE, "five_hour": {"utilization": 0, "resets_at": None}}

    reading = read_live_usage(
        token="t", fetch=lambda url, headers: idle, cache_path=tmp_path / "c.json"
    )

    assert reading is not None
    assert reading.session_pct == 0 and reading.resets_at is None
    assert may_start_unit(reading).may_start
