"""A refusal that asks for no wait does not widen the time a reading is kept.

The endpoint answering 429 with `Retry-After: 0` says nothing about the rate of calls, so
the time a good reading is kept stays where it was; any other refusal doubles it up to a
ceiling that defaults to thirty minutes, and a longer named retry time still wins
(spec: usage-api-observability). Only the endpoint and the home directory are faked.
"""

import json
from datetime import UTC, datetime, timedelta

from agent_build_kit.config import ClaudeLimitsConfig
from agent_build_kit.pipeline.usage_calls import interval_line
from agent_build_kit.pipeline.usage_guard import (
    DEFAULT_COOLDOWN,
    current_cache_interval,
    current_usage,
    next_call_at,
)
from tests.usage_host import Host, configure, refusal

MINUTE = timedelta(minutes=1)


def kept_minutes(host: Host) -> float:
    return current_cache_interval(host.calls_file).kept / MINUTE


def refused_with(host: Host, **headers: str) -> None:
    host.answers = [refusal(**headers)]
    current_usage()


def quiet_refusal(at: datetime) -> dict:
    return {
        "at": at.isoformat(),
        "caller": "guard",
        "outcome": "rate_limited",
        "status": 429,
        "latency_ms": 120,
        "headers": {},
        "age_seconds": None,
    }


def test_a_refusal_with_a_retry_time_of_zero_leaves_the_time_at_the_base(host: Host) -> None:
    refused_with(host, Retry_After="0")

    interval = current_cache_interval(host.calls_file)

    assert interval.kept == 15 * MINUTE
    assert interval.reason == "configured"


def test_a_refusal_without_a_header_doubles_once_and_stops_at_the_default_ceiling(
    host: Host,
) -> None:
    now = datetime.now(UTC)
    host.seed(quiet_refusal(now - 3 * MINUTE))
    assert kept_minutes(host) == 30

    host.seed(quiet_refusal(now - 3 * MINUTE), quiet_refusal(now - MINUTE))

    assert kept_minutes(host) == 30


def test_a_longer_named_retry_time_wins_past_the_ceiling(host: Host) -> None:
    refused_with(host, Retry_After="0")
    assert kept_minutes(host) == 15

    refused_with(host, Retry_After="3600")

    assert kept_minutes(host) == 60


def test_the_cool_down_after_a_retry_time_of_zero_is_the_default_and_the_next_call_is_a_base_away(
    host: Host,
) -> None:
    before = datetime.now(UTC)
    refused_with(host, Retry_After="0")

    cooldown = datetime.fromisoformat(json.loads(host.cache.read_text())["cooldown_until"])
    allowed = next_call_at(host.calls_file, now=datetime.now(UTC))

    assert abs(cooldown - (before + DEFAULT_COOLDOWN)) < timedelta(seconds=30)
    assert allowed is not None
    assert abs(allowed - (before + 15 * MINUTE)) < timedelta(seconds=30)


def test_a_time_of_thirty_minutes_halves_after_a_quiet_but_a_zero_refusal_does_not_widen(
    host: Host,
) -> None:
    host.seed(quiet_refusal(datetime.now(UTC) - 31 * MINUTE))
    assert current_cache_interval(host.calls_file).reason == "quiet"
    assert kept_minutes(host) == 15

    refused_with(host, Retry_After="0")

    assert kept_minutes(host) == 15
    assert "did not widen" in interval_line(current_cache_interval(host.calls_file))


def test_the_ceiling_defaults_to_thirty_minutes_and_a_configured_value_above_it_is_kept(
    host: Host,
) -> None:
    assert ClaudeLimitsConfig().usage_cache_max_minutes == 30

    configure(usage_cache_max_minutes=90)
    host.seed(*(quiet_refusal(datetime.now(UTC) - n * MINUTE) for n in (5, 4, 3, 2, 1)))

    assert kept_minutes(host) == 90
