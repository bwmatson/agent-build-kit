"""The record of every use of the usage endpoint, and the call rate read from it.

The endpoint rate-limits and does not say how often it allows calls, so each
call and each reading answered from the cache is appended to `usage-calls.jsonl`
in the state directory: when, who asked, the outcome, the status, the latency and
the rate-limit or retry headers of the answer. It belongs to no change, so it is
kept for a week and never rolled up. It holds no token. The reading derived from
it is shown by the status command and exported as metrics.
"""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

from pydantic import ValidationError

from agent_build_kit import telemetry
from agent_build_kit.model import Frozen

CALLS_NAME = "usage-calls.jsonl"
KEPT = timedelta(days=7)
REFUSED = "rate_limited"
CACHE = "cache"
# A refusal this soon after a successful call means that call's rate was not safe.
SAFE_MARGIN = timedelta(seconds=60)
BEFORE_REFUSAL = timedelta(minutes=15)


class UsageCall(Frozen):
    """One line of the record: a call to the endpoint, or a reading answered from the cache."""

    at: datetime
    caller: str
    outcome: str  # ok, rate_limited, timeout, error or cache
    status: int | None = None
    latency_ms: int = 0
    headers: dict[str, str] = {}
    age_seconds: int | None = None  # a cached reading's age
    session_pct: int | None = None  # the percentages an answered call read
    weekly_pct: int | None = None


class Refusal(Frozen):
    at: datetime
    quiet_seconds: int | None  # since the call before it, None when there was none
    calls_before: int  # calls in the fifteen minutes before it


class CallWindow(Frozen):
    calls: int
    by_outcome: dict[str, int]
    by_caller: dict[str, int]
    cache_share: float
    refusals: tuple[Refusal, ...]


class CallRate(Frozen):
    hour: CallWindow
    day: CallWindow
    last_refusal_at: datetime | None
    safe_interval_seconds: int | None


def rate_limit_headers(headers: object) -> dict[str, str]:
    """The headers of an answer whose names concern rate limits or retrying."""
    try:
        pairs = list(headers.items())  # type: ignore[attr-defined]
    except AttributeError:
        return {}
    return {
        str(name): str(value)
        for name, value in pairs
        if any(word in str(name).lower() for word in ("ratelimit", "rate-limit", "retry"))
    }


def read_calls(path: Path) -> list[UsageCall]:
    """The record's lines, skipping any that cannot be read."""
    try:
        text = path.read_text()
    except OSError:
        return []
    calls = []
    for raw in text.splitlines():
        try:
            calls.append(UsageCall.model_validate(json.loads(raw)))
        except (ValueError, ValidationError):
            continue
    return calls


def record_call(path: Path, call: UsageCall) -> None:
    """Append `call`, drop what is older than a week, and export the figures."""
    now = datetime.now(UTC)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            existing = path.read_text().splitlines()
        except OSError:
            existing = []
        fresh = [raw for raw in existing if raw and _fresh(raw, now)]
        fresh.append(call.model_dump_json())
        if len(fresh) == len(existing) + 1:
            with path.open("a") as handle:
                handle.write(fresh[-1] + "\n")
        else:
            path.write_text("".join(raw + "\n" for raw in fresh))
    except OSError:
        return
    telemetry.count("abk.usage.calls", 1, outcome=call.outcome, caller=call.caller)
    interval = derive_rate(read_calls(path), now=now).safe_interval_seconds
    if interval is not None:
        telemetry.level("abk.usage.safe_interval", interval)


def _fresh(raw: str, now: datetime) -> bool:
    try:
        return datetime.fromisoformat(json.loads(raw)["at"]) > now - KEPT
    except (ValueError, KeyError, TypeError):
        return False


def _window(calls: list[UsageCall], since: datetime) -> CallWindow:
    inside = [c for c in calls if c.at > since]
    by_outcome: dict[str, int] = {}
    by_caller: dict[str, int] = {}
    for c in inside:
        by_outcome[c.outcome] = by_outcome.get(c.outcome, 0) + 1
        by_caller[c.caller] = by_caller.get(c.caller, 0) + 1
    endpoint = [c for c in calls if c.outcome != CACHE]
    refusals = []
    for index, c in enumerate(endpoint):
        if c.outcome != REFUSED or c.at <= since:
            continue
        before = endpoint[index - 1] if index else None
        refusals.append(
            Refusal(
                at=c.at,
                quiet_seconds=int((c.at - before.at).total_seconds()) if before else None,
                calls_before=sum(1 for o in endpoint[:index] if o.at >= c.at - BEFORE_REFUSAL),
            )
        )
    return CallWindow(
        calls=len(inside),
        by_outcome=by_outcome,
        by_caller=by_caller,
        cache_share=by_outcome.get(CACHE, 0) / len(inside) if inside else 0.0,
        refusals=tuple(refusals),
    )


def _safe_interval(endpoint: list[UsageCall]) -> int | None:
    """The shortest gap between consecutive successful calls that no refusal came
    between or followed within the margin."""
    shortest: int | None = None
    previous: UsageCall | None = None
    for index, c in enumerate(endpoint):
        if c.outcome != "ok":
            if c.outcome == REFUSED:
                previous = None
            continue
        refused_after = any(
            later.outcome == REFUSED and later.at - c.at <= SAFE_MARGIN
            for later in endpoint[index + 1 :]
        )
        if previous is not None and not refused_after:
            gap = int((c.at - previous.at).total_seconds())
            shortest = gap if shortest is None else min(shortest, gap)
        previous = c
    return shortest


def derive_rate(calls: list[UsageCall], *, now: datetime) -> CallRate:
    ordered = sorted((c for c in calls if c.at <= now), key=lambda c: c.at)
    day_since = now - timedelta(days=1)
    day = _window(ordered, day_since)
    in_day = [c for c in ordered if c.at > day_since and c.outcome != CACHE]
    return CallRate(
        hour=_window(ordered, now - timedelta(hours=1)),
        day=day,
        last_refusal_at=day.refusals[-1].at if day.refusals else None,
        safe_interval_seconds=_safe_interval(in_day),
    )


class CacheInterval(Frozen):
    """How long a good reading is kept now, and what set it: `refusal`, `quiet` or `configured`."""

    kept: timedelta
    reason: str


def cache_interval(
    calls: list[UsageCall], *, now: datetime, base: timedelta, maximum: timedelta
) -> CacheInterval:
    """Replay the record: each refusal doubles the time up to `maximum`, each further
    stretch of that time without one halves it, never below `base`. A retry time a
    refusal names holds while it lasts, even past `maximum`."""
    maximum = max(base, maximum)
    kept = base
    since: datetime | None = None
    reason = "configured"

    def settle(until: datetime) -> None:
        nonlocal kept, since, reason
        while since is not None and kept > base and until - since >= kept:
            since += kept
            kept = max(base, kept / 2)
            reason = "quiet"

    refusals = sorted(
        (c for c in calls if c.outcome == REFUSED and c.at <= now), key=lambda c: c.at
    )
    for refusal in refusals:
        settle(refusal.at)
        kept = min(kept * 2, maximum)
        since = refusal.at
        reason = "refusal"
    settle(now)
    if refusals and now - refusals[-1].at < _retry_after(refusals[-1]):
        kept = max(kept, _retry_after(refusals[-1]))
    return CacheInterval(kept=kept, reason=reason)


def _retry_after(call: UsageCall) -> timedelta:
    for name, value in call.headers.items():
        if name.lower() == "retry-after":
            try:
                return timedelta(seconds=max(0.0, float(value)))
            except ValueError:
                return timedelta(0)
    return timedelta(0)


def most_added(
    calls: list[UsageCall],
    window: Literal["session", "weekly"],
    *,
    minutes: float,
    floor: float,
    margin: int,
) -> float:
    """The most percentage points `window` could have gained in `minutes`: the fastest climb
    between consecutive answered calls in the record, no slower than `floor`, plus `margin`."""
    raise NotImplementedError


def interval_line(interval: CacheInterval) -> str:
    minutes = round(interval.kept.total_seconds() / 60)
    why = {
        "refusal": "set after a refusal",
        "quiet": "lowered after a quiet spell",
        "configured": "the configured time",
    }[interval.reason]
    return f"usage cache: kept {minutes} minutes, {why}"


def rate_line(rate: CallRate) -> str:
    interval = rate.safe_interval_seconds
    shown = "none" if interval is None else f"{interval}s"
    return (
        f"usage calls: {rate.hour.calls} in the last hour, {len(rate.hour.refusals)} refused, "
        f"{round(rate.hour.cache_share * 100)}% from the cache, safe interval {shown}"
    )
