"""A decision answered from Claude Code's own cache is recorded as `claude-json`, counted apart.

The line holds the caller and the block's age and no status or token; it is not a call to the
endpoint, so the next permitted call, the refusal bookkeeping and the safe interval ignore it; the
call-rate line prints its share beside the cache's (spec: usage-pause).
"""

from datetime import UTC, datetime, timedelta

import pytest

from agent_build_kit.pipeline.usage_calls import (
    CLAUDE_JSON,
    UsageCall,
    derive_rate,
    rate_line,
)
from agent_build_kit.pipeline.usage_guard import decide_start, next_call_at
from tests.usage_host import SECRET, Host, configure, pause_at, payload

NOW = datetime(2030, 1, 2, 12, 0, tzinfo=UTC)


def line(at: datetime, outcome: str = "ok", *, status: int | None = None) -> dict:
    return {
        "at": at.isoformat(),
        "caller": "guard",
        "outcome": outcome,
        "status": status if status is not None else (200 if outcome == "ok" else None),
        "latency_ms": 120,
        "headers": {},
        "age_seconds": 60 if outcome in ("cache", CLAUDE_JSON) else None,
    }


def ago(**delta: float) -> datetime:
    return NOW - timedelta(**delta)


def calls_of(*lines: dict) -> list[UsageCall]:
    return [UsageCall.model_validate(each) for each in lines]


def test_the_line_holds_the_caller_and_the_age_and_no_status_or_token(host: Host) -> None:
    configure(**pause_at(92))
    host.keep_reading(40 * timedelta(minutes=1), payload(session=90.0))
    host.keep_editor_reading(timedelta(minutes=6))

    decide_start()

    (written,) = [each for each in host.lines() if each["outcome"] == CLAUDE_JSON]
    assert written["caller"] == "guard"
    assert 6 * 60 - 5 <= written["age_seconds"] <= 6 * 60 + 30
    assert written["status"] is None
    assert not written["headers"]
    assert SECRET not in host.calls_file.read_text()


def test_the_next_permitted_call_is_the_same_with_or_without_a_line(host: Host) -> None:
    configure(**pause_at(92))
    ok = line(datetime.now(UTC) - timedelta(minutes=10))
    host.seed(ok)
    without = next_call_at(host.calls_file, now=datetime.now(UTC))

    host.seed(ok, line(datetime.now(UTC) - timedelta(minutes=1), CLAUDE_JSON))

    assert next_call_at(host.calls_file, now=datetime.now(UTC)) == without
    assert without is not None


def test_a_line_changes_neither_the_refusal_bookkeeping_nor_the_safe_interval() -> None:
    endpoint = [
        line(ago(hours=5)),
        line(ago(hours=4, minutes=50)),
        line(ago(minutes=40)),
        line(ago(minutes=38)),
        line(ago(minutes=36)),
        line(ago(minutes=28), "rate_limited", status=429),
    ]
    between = [line(ago(hours=4, minutes=55), CLAUDE_JSON), line(ago(minutes=30), CLAUDE_JSON)]

    plain = derive_rate(calls_of(*endpoint), now=NOW)
    mixed = derive_rate(calls_of(*endpoint, *between), now=NOW)

    assert mixed.safe_interval_seconds == plain.safe_interval_seconds
    assert mixed.day.refusals == plain.day.refusals
    assert mixed.hour.refusals == plain.hour.refusals
    assert mixed.last_refusal_at == plain.last_refusal_at
    assert mixed.hour.refusals[0].calls_before == 3
    assert mixed.day.by_outcome[CLAUDE_JSON] == 2


def test_the_rate_line_prints_the_cache_s_share_and_the_block_s_apart() -> None:
    calls = [
        *(line(ago(minutes=m)) for m in (50, 40, 30)),
        *(line(ago(minutes=m), "cache") for m in (25, 24, 23, 22)),
        *(line(ago(minutes=m), CLAUDE_JSON) for m in (15, 14, 13, 12, 11)),
    ]

    rate = derive_rate(calls_of(*calls), now=NOW)

    assert rate_line(rate) == (
        "usage calls: 12 in the last hour, 0 refused, 33% from the cache, "
        "42% from claude.json, safe interval 600s"
    )
    assert rate.hour.cache_share == pytest.approx(4 / 12)


def test_a_block_answer_does_not_move_the_cache_s_numerator() -> None:
    cache_only = [line(ago(minutes=m), "cache") for m in (25, 24)] + [line(ago(minutes=40))]
    with_block = [*cache_only, line(ago(minutes=10), CLAUDE_JSON)]

    rate = derive_rate(calls_of(*with_block), now=NOW)

    assert rate.hour.by_outcome["cache"] == 2
    assert rate.hour.cache_share == pytest.approx(2 / 4)
    assert "from claude.json" in rate_line(rate)
