"""Whether there is room in the Claude usage window to start another unit.

The account is on a subscription, so the constraint isn't dollars — it's the
plan's usage window, shared with the user's own interactive sessions. Credits
are enabled past the plan limit, which means running to 100% spends real money
instead of stopping. So unattended work stops starting new units at
the pause percent of the window that is full (`usage_pause_pct`, 70 by default,
in the `session` or `weekly` section of `runtimes.claude_code.limits`) and
schedules a resume.

**The threshold need not be flat.** Quota left unused when a window resets is
simply lost, and the reasons to hold back — room for units already running, room
for the user's own sessions — shrink as the reset approaches. So a window whose
`usage_pause_ceiling_pct` is above its `usage_pause_pct` ramps from the one up
to the other over the last `usage_relief_fraction` of that window, and
each window is measured against *its own* reset: the five-hour session and the
seven-day week ramp independently, each with its own relief fraction and resume
buffer. A window with no ceiling, or one equal to
its pause percent, does not ramp: its threshold is that one number all the way
to the reset. The ceiling stays below 100 so relief never reaches the point
where credits start paying.

**Where the numbers come from**, in the order tried:

1. **The live endpoint**, `GET api.anthropic.com/api/oauth/usage` with the
   OAuth token Claude Code already stores and an `anthropic-beta:
   oauth-2025-04-20` header. This is what the `/usage` panel itself calls. It
   answers with both windows' utilization, their reset times, and the credits
   state. Undocumented, so it can change or disappear — which is why there is
   a fallback, and why anything unrecognised reads as unknown.
2. **Claude Code's state file** (`<account dir>/.claude.json` with an account
   set, else `~/.claude.json`) and its `cachedUsageUtilization`, the same numbers cached
   locally. Only refreshed when an *interactive* session talks to the API — a
   headless run does not refresh it (verified) — so it is stale exactly when
   the runner is working alone, and readings past `MAX_ANCHOR_AGE` are
   discarded rather than trusted.
3. **Nothing.** Which pauses.

Claude Code itself exposes no supported way to read this: no `claude usage`
subcommand, no rate-limit fields in `claude -p --output-format json`, and the
statusline hook (which does receive them) only runs in interactive sessions.

The rule this module enforces: **an unknown reading pauses.** Assuming headroom
nobody has measured is how an unattended pipeline quietly spends credits
overnight.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Literal

from agent_build_kit import claude_account, telemetry
from agent_build_kit.config import (
    CLAUDE_CODE,
    ClaudeLimitsConfig,
    GateConfig,
    ProviderLimitsConfig,
    RuntimeConfig,
    UsageWindowConfig,
    active,
    active_root,
)
from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.file_lock import atomic_write_text, file_lock, try_file_lock
from agent_build_kit.pipeline.pause import UNKNOWN_RETRY
from agent_build_kit.pipeline.usage_allowances import (
    ALLOWANCES_NAME,
    SESSION_WINDOW,
    WEEKLY_WINDOW,
    WINDOWS,
    allowance_for,
    read_allowances,
)
from agent_build_kit.pipeline.usage_calls import (
    CACHE,
    CALLS_NAME,
    CLAUDE_JSON,
    CacheInterval,
    UsageCall,
    cache_interval,
    is_endpoint_call,
    most_added,
    rate_limit_headers,
    read_calls,
    record_call,
)
from agent_build_kit.pipeline.usage_ledger import LEDGER_NAME, read_ledger, spend_times
from agent_build_kit.runtimes.base import AgentInterrupted, AgentRateLimited, Run
from agent_build_kit.runtimes.providers import ProviderReading

USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
OAUTH_BETA_HEADER = "oauth-2025-04-20"
CREDENTIALS_PATH = Path.home() / ".claude" / ".credentials.json"
DEFAULT_ANCHOR_PATH = Path.home() / ".claude.json"

log = logging.getLogger(__name__)

# The causes already logged by this process, which is a tick: one line per cause,
# however many readers meet the failure.
_logged_failures: set[str] = set()

# After a rate-limit answer that names no time, no call is made for this long.
DEFAULT_COOLDOWN = timedelta(minutes=5)

# A timeout or connection error is retried once, after this many seconds.
RETRY_DELAY_SECONDS = 0.5

# How old a *cached-file* reading may be before it says nothing useful. The
# five-hour window is the shorter of the two, so an hour is already a
# meaningful fraction of it. Live readings are exempt: they were just taken.
MAX_ANCHOR_AGE = timedelta(hours=1)

# A window's start is its reset minus its length (`usage_allowances` holds the
# lengths, which the endpoint doesn't report), and that is all the ramp needs.

# The longest resume a pause may schedule. A weekly window can reset days out,
# and `pause_until` never shortens an existing pause, so an honest "resume when
# the week resets" would wedge the pipeline for that long — this makes it
# re-read instead. Being woken to pause again is cheap; sleeping through a
# reset is not.
MAX_SCHEDULED_PAUSE = timedelta(hours=6)

Fetch = Callable[[str, dict[str, str]], object]


class Window(Frozen):
    """One usage window as the ramp sees it: how full, and when it resets."""

    name: Literal["session", "weekly"]
    used_pct: int
    resets_at: datetime | None
    length: timedelta


class UsageReading(Frozen):
    """Where the usage windows stood, and how we came to know it."""

    session_pct: int
    weekly_pct: int
    # None when no five-hour window is open: nothing has been used since the
    # last one ended, so there is nothing to reset. Not "unknown".
    resets_at: datetime | None
    # The same, for the seven-day window. Defaulted because the older readings
    # cached on disk predate it; absent reads as "no window open", which only
    # ever costs the weekly ramp, never headroom nobody measured.
    weekly_resets_at: datetime | None = None
    observed_at: datetime
    source: str
    credits_enabled: bool
    credits_used_dollars: float
    spend_limit_reached: bool

    @property
    def age(self) -> timedelta:
        return datetime.now(UTC) - self.observed_at

    @property
    def is_live(self) -> bool:
        return self.source == "live"

    @property
    def session_resets_at(self) -> datetime | None:
        """`resets_at` under the name the ramp uses, now that there are two."""
        return self.resets_at

    @property
    def windows(self) -> tuple[Window, ...]:
        """Both windows, weekly first — the order `may_start_unit` reports
        them in, so the longer window is named when both are over."""
        return (
            Window(
                name="weekly",
                used_pct=self.weekly_pct,
                resets_at=self.weekly_resets_at,
                length=WEEKLY_WINDOW,
            ),
            Window(
                name="session",
                used_pct=self.session_pct,
                resets_at=self.resets_at,
                length=SESSION_WINDOW,
            ),
        )


class Decision(Frozen):
    """Whether to start another unit, and when to look again if not."""

    may_start: bool
    reason: str
    resume_at: datetime | None = None
    # When the session window of the reading behind an allowance resets: where a caller
    # that wants a time to look again at falls back to when the decision names none.
    resets_at: datetime | None = None

    @property
    def resume_after_seconds(self) -> float:
        if self.resume_at is None:
            return 0.0
        return max(1.0, (self.resume_at - datetime.now(UTC)).total_seconds())


class UsageLedger:
    """What this runner has spent, as a JSONL file it appends to.

    Not part of the start/stop decision any more — the live endpoint answers
    that directly. It stays because the run log should be able to say what a
    unit cost, and because it is the only per-unit attribution available: the
    endpoint reports the account, not who spent it.
    """

    def __init__(self, path: Path) -> None:
        self.path = path

    def record(self, cost_usd: float, *, unit: str, at: datetime | None = None) -> None:
        at = at or datetime.now(UTC)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a") as handle:
            handle.write(
                json.dumps({"at": at.isoformat(), "cost_usd": cost_usd, "unit": unit}) + "\n"
            )

    def _entries_since(self, since: datetime) -> list[dict]:
        if not self.path.exists():
            return []

        entries = []
        for line in self.path.read_text().splitlines():
            try:
                entry = json.loads(line)
                if datetime.fromisoformat(entry["at"]) >= since:
                    entries.append(entry)
            except (ValueError, KeyError, TypeError):
                # A half-written line from a killed process. Skipping it loses
                # one run's cost, which is a smaller error than discarding the
                # rest of the ledger.
                continue
        return entries

    def spend_since(self, since: datetime) -> float:
        return sum(float(e["cost_usd"]) for e in self._entries_since(since))

    def runs_since(self, since: datetime) -> int:
        return len(self._entries_since(since))


def _http_get_json(url: str, headers: dict[str, str]) -> object:
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=20) as response:  # noqa: S310
        return json.load(response)


def _credentials_path() -> Path:
    """The credentials file read by default: the account's when one is set, else the constant."""
    return CREDENTIALS_PATH if claude_account.is_default() else claude_account.credentials_path()


def _state_file() -> Path:
    """Claude Code's own state file read by default: the account's when one is set."""
    return DEFAULT_ANCHOR_PATH if claude_account.is_default() else claude_account.state_file()


def read_oauth_token(path: Path | None = None) -> str | None:
    """Find Claude Code's stored OAuth token.

    Read-only, and the value is never logged or written anywhere by this
    module — it goes straight into the Authorization header.
    """
    from_env = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN")
    if from_env:
        return from_env

    try:
        raw = json.loads((path or _credentials_path()).read_text())
    except (OSError, ValueError):
        return None

    def find(node: object) -> str | None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key in ("accessToken", "access_token", "oauth_access_token") and isinstance(
                    value, str
                ):
                    return value
                found = find(value)
                if found:
                    return found
        return None

    return find(raw)


def _reading_from_payload(
    payload: object, *, observed_at: datetime, source: str
) -> UsageReading | None:
    """Build a reading, or None if the response isn't a shape we recognise."""
    if not isinstance(payload, dict):
        return None

    try:
        session = payload["five_hour"]
        weekly = payload["seven_day"]
        credits = payload.get("extra_usage") or {}

        return UsageReading(
            session_pct=int(float(session["utilization"])),
            weekly_pct=int(float(weekly["utilization"])),
            resets_at=_reset_time(session.get("resets_at")),
            weekly_resets_at=_reset_time(weekly.get("resets_at")),
            observed_at=observed_at,
            source=source,
            credits_enabled=bool(credits.get("is_enabled", False)),
            # used_credits is in cents: 1324.0 is $13.24.
            credits_used_dollars=float(credits.get("used_credits") or 0) / 100,
            spend_limit_reached=bool(credits.get("spend_limit_reached", False)),
        )
    except (KeyError, TypeError, ValueError):
        return None


def _reset_time(value: object) -> datetime | None:
    """A window's reset time; None when no window is open.

    The endpoint reports `resets_at: null` once a five-hour window has ended
    and nothing has started another. Parsing that as a failure read the usage
    as unknown, which pauses — and a paused pipeline never starts a window, so
    it stays null until someone uses Claude by hand. That stops every tick for
    hours, or overnight.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(f"resets_at is {type(value).__name__}, not a timestamp")
    return datetime.fromisoformat(value)


def _resume_after(reading: UsageReading) -> datetime:
    """When to look again after refusing: just past the reset, or — with no
    window open to reset — after the usual retry interval."""
    now = datetime.now(UTC)
    if reading.resets_at is None or reading.resets_at <= now:
        return now + UNKNOWN_RETRY
    return reading.resets_at


class Band(Frozen):
    """One window's settings: the pause percent, the ceiling it rises to, and
    the two numbers that shape the rise and the wait for it."""

    pause_pct: int
    ceiling_pct: int
    # The trailing fraction of the window the rise is spread over.
    relief_fraction: float = 0.25
    # Room above current usage the threshold must offer before a resume.
    resume_buffer_pct: int = 5

    @property
    def ramps(self) -> bool:
        """Whether the threshold moves at all. With the ceiling at the pause
        percent it cannot, so there is nothing to compute and nothing to say."""
        return self.ceiling_pct > self.pause_pct


class Limits(Frozen):
    """What the ramp is made of, one band per window, passed in rather than
    read from the active config, so the arithmetic can be tested without one."""

    session: Band
    weekly: Band

    def band(self, window: Window) -> Band:
        return self.session if window.name == "session" else self.weekly

    @classmethod
    def configured(cls) -> Limits:
        claude = claude_limits()
        return cls(session=_band(claude.session), weekly=_band(claude.weekly))


def _band(window: UsageWindowConfig) -> Band:
    return Band(
        pause_pct=window.usage_pause_pct,
        ceiling_pct=window.usage_ceiling_pct,
        relief_fraction=window.usage_relief_fraction,
        resume_buffer_pct=window.usage_resume_buffer_pct,
    )


def threshold_at(window: Window, *, now: datetime, limits: Limits) -> int:
    """The percent this window may be run to at `now`.

    Its pause percent for most of the window, then a straight line up to its
    ceiling, reached at the reset. A window with no reset time isn't open, so
    nothing is close to running out: the base applies. So does a window whose
    ceiling is its pause percent: the line would be flat, and is not drawn.
    """
    band = limits.band(window)
    if window.resets_at is None or not band.ramps:
        return band.pause_pct

    span = window.length * band.relief_fraction
    remaining = window.resets_at - now
    if remaining >= span:
        return band.pause_pct
    if remaining <= timedelta(0):
        return band.ceiling_pct

    elapsed = 1 - remaining / span
    return round(band.pause_pct + (band.ceiling_pct - band.pause_pct) * elapsed)


def relief_at(window: Window, *, now: datetime, limits: Limits) -> datetime | None:
    """When the ramp will first offer room to work, or None if it never will.

    "Room" is the window's current usage plus `resume_buffer_pct`: waking at
    the moment the threshold merely equals what is already used would start a
    unit with nothing left to finish it. Usage only grows inside a window, so
    this is the earliest the answer can change — never a promise that it has.
    """
    if window.resets_at is None:
        return None

    band = limits.band(window)
    target = window.used_pct + band.resume_buffer_pct
    if target <= band.pause_pct:
        return now
    # A window that does not ramp never offers more than its pause percent, so
    # only its reset can bring room back.
    if not band.ramps or target > band.ceiling_pct:
        return None

    reach = (target - band.pause_pct) / (band.ceiling_pct - band.pause_pct)
    span = window.length * band.relief_fraction
    return max(now, window.resets_at - span * (1 - reach))


def token_expired(path: Path | None = None, *, now: datetime | None = None) -> bool:
    """Whether the saved OAuth access token has passed its `expiresAt`.

    False when that cannot be read: the refresh below is only for the state it
    is known to fix, not a general retry.
    """
    path = path or _credentials_path()
    try:
        raw = json.loads(path.read_text())
    except (OSError, ValueError):
        return False
    oauth = raw.get("claudeAiOauth", raw) if isinstance(raw, dict) else {}
    expires = oauth.get("expiresAt") if isinstance(oauth, dict) else None
    if not isinstance(expires, (int, float)):
        return False
    return datetime.fromtimestamp(expires / 1000, tz=UTC) <= (now or datetime.now(UTC))


def refresh_login() -> None:
    """Have Claude Code refresh the OAuth token, with the smallest call it takes.

    The token lasts hours and is refreshed only when Claude Code talks to the
    API. The pipeline reads usage *before* any Claude run, so overnight it went
    round in a circle: the token expired, the usage read was refused, the tick
    paused, and nothing ran Claude to refresh it — every minute from the
    window's reset until someone opened a session. One tiny haiku call breaks
    the circle; it is made only once the token has expired.

    The call itself is the Claude Code adapter's, the one place a `claude`
    argv is built. Imported here rather than at the top: the adapter reads
    usage through this module.
    """
    from agent_build_kit.runtimes import claude_code

    claude_code.refresh_login()


def claude_limits() -> ClaudeLimitsConfig:
    return active().runtimes.get(CLAUDE_CODE, RuntimeConfig()).limits


def current_cache_interval(calls_file: Path) -> CacheInterval:
    """How long a good reading is kept now, from the record and the configured bounds."""
    limits = claude_limits()
    return cache_interval(
        read_calls(calls_file),
        now=datetime.now(UTC),
        base=timedelta(minutes=limits.usage_cache_minutes),
        maximum=timedelta(minutes=limits.usage_cache_max_minutes),
    )


def _cache_file() -> Path:
    root = active_root()
    state = (
        root / active().planning.state_dir if root else Path.home() / ".cache" / "agent-build-kit"
    )
    return state / "usage-cache.json"


def _load_cache(path: Path) -> dict:
    try:
        cached = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    if not isinstance(cached, dict) or cached.get("account") != claude_account.account_key():
        # A reading, cool-down or fallback of another account (or of none while one is in use,
        # or of one while none is) is never served; the next write replaces it.
        return {}
    return cached


def _write_cache(path: Path, body: dict) -> None:
    """Write the cache file whole: a reader outside the lock never sees half of it. The
    account is recorded only when one is set."""
    if (account := claude_account.account_key()) is not None:
        body = {**body, "account": account}
    atomic_write_text(path, json.dumps(body, indent=2))


def _kept_reading(cached: dict) -> UsageReading | None:
    """The reading kept in the cache file, labelled as what it is: not live."""
    try:
        fetched_at = datetime.fromisoformat(cached["fetched_at"])
    except (KeyError, TypeError, ValueError):
        return None
    return _reading_from_payload(cached, observed_at=fetched_at, source="cache")


def _cooldown_until(cached: dict) -> datetime | None:
    """When the cool-down kept in the cache file ends, or None when it holds none."""
    try:
        return datetime.fromisoformat(cached["cooldown_until"])
    except (KeyError, TypeError, ValueError):
        return None


def _cooling(cached: dict, now: datetime) -> bool:
    """Whether a cool-down kept in the cache file is in force at `now`."""
    until = _cooldown_until(cached)
    return until is not None and until > now


def _cooldown_seconds(error: urllib.error.HTTPError) -> float:
    try:
        named = float(error.headers.get("Retry-After", ""))
    except (AttributeError, TypeError, ValueError):
        return DEFAULT_COOLDOWN.total_seconds()
    return named if named > 0 else DEFAULT_COOLDOWN.total_seconds()


def _past_reset(reading: UsageReading, now: datetime) -> bool:
    """Whether a window the reading describes has reset since it was taken."""
    return any(
        w.resets_at is not None and reading.observed_at < w.resets_at <= now
        for w in reading.windows
    )


def read_live_usage(
    *,
    token: str | None = None,
    fetch: Fetch = _http_get_json,
    cache_path: Path | None = None,
    ttl: timedelta | None = None,
    expired: Callable[[], bool] | None = None,
    refresh: Callable[[], None] | None = None,
    caller: str | None = None,
) -> UsageReading | None:
    """Ask the endpoint where the windows stand, or None if it can't say.

    A good answer is kept in `cache_path` for `ttl` (by default the adaptive cache
    time of `current_cache_interval`),
    so every reader in every process shares it, and never past the reset of a
    window it describes. A rate-limit answer starts a cool-down, kept in the same
    file, during which no call is made; a timeout or connection error is retried
    once. When the call fails the last good reading stands in while it is younger
    than the configured fallback age, labelled `cache`. The token is never written
    there.
    """
    cache_path = cache_path or _cache_file()
    calls_file = cache_path.parent / CALLS_NAME
    caller = caller or _caller.get()
    limits = claude_limits()
    if ttl is None:
        ttl = current_cache_interval(calls_file).kept
    fallback_age = timedelta(minutes=limits.usage_fallback_minutes)
    now = datetime.now(UTC)

    cached = _load_cache(cache_path)
    kept = _kept_reading(cached)

    def last_good() -> UsageReading | None:
        if kept is None or now - kept.observed_at >= fallback_age or _past_reset(kept, now):
            return None
        return kept

    def _refresh_under_lock() -> UsageReading | None:
        nonlocal token
        if _cooling(cached, now):
            return last_good()

        telemetry.count("abk.usage.cache", 1, event="miss")
        given = token
        token = token or read_oauth_token()
        if not token:
            return None

        def ask(bearer: str) -> object:
            started = time.monotonic()
            asked = datetime.now(UTC)
            status: int | None = 200
            headers: object = None
            outcome = "ok"
            read: UsageReading | None = None
            try:
                answer = fetch(
                    USAGE_URL,
                    {"Authorization": f"Bearer {bearer}", "anthropic-beta": OAUTH_BETA_HEADER},
                )
                read = _reading_from_payload(answer, observed_at=asked, source="live")
                return answer
            except Exception as error:
                if isinstance(error, urllib.error.HTTPError):
                    status, headers = error.code, error.headers
                    outcome = "rate_limited" if error.code == 429 else "error"
                else:
                    status = None
                    reason = error.reason if isinstance(error, urllib.error.URLError) else error
                    outcome = "timeout" if isinstance(reason, TimeoutError) else "error"
                raise
            finally:
                record_call(
                    calls_file,
                    UsageCall(
                        account=claude_account.account_key(),
                        at=asked,
                        caller=caller,
                        outcome=outcome,
                        status=status,
                        latency_ms=int((time.monotonic() - started) * 1000),
                        headers=rate_limit_headers(headers),
                        session_pct=read.session_pct if read else None,
                        weekly_pct=read.weekly_pct if read else None,
                    ),
                )

        def failed(error: Exception) -> UsageReading | None:
            if isinstance(error, urllib.error.HTTPError):
                cause = f"HTTP {error.code}"
                if error.code == 429:
                    until = now + timedelta(seconds=_cooldown_seconds(error))
                    try:
                        cache_path.parent.mkdir(parents=True, exist_ok=True)
                        _write_cache(cache_path, {**cached, "cooldown_until": until.isoformat()})
                    except (OSError, TypeError):
                        pass
            else:
                cause = type(error).__name__
            if cause not in _logged_failures:
                _logged_failures.add(cause)
                log.warning(
                    "the usage endpoint failed (%s); using the last good reading if any", cause
                )
            return last_good()

        try:
            payload = ask(token)
        except Exception as error:
            rate_limited = isinstance(error, urllib.error.HTTPError) and error.code == 429
            if rate_limited:
                return failed(error)
            # An expired token is the one failure with a known fix; see
            # `refresh_login`. Only for the saved token, never one passed in, and
            # whatever the failure was: an expired token is answered with a 401.
            if given is None and (expired or token_expired)():
                (refresh or refresh_login)()
                fresh = read_oauth_token()
                if not fresh or fresh == token:
                    return failed(error)
                retry_with = fresh
            elif isinstance(error, OSError) and not isinstance(error, urllib.error.HTTPError):
                # A timeout or a connection error: once more after a short delay.
                time.sleep(RETRY_DELAY_SECONDS)
                retry_with = token
            else:
                return failed(error)
            try:
                payload = ask(retry_with)
            except Exception as again:
                return failed(again)

        reading = _reading_from_payload(payload, observed_at=now, source="live")
        if reading is None:
            return None

        if isinstance(payload, dict):
            try:
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                _write_cache(cache_path, {**payload, "fetched_at": now.isoformat()})
            except (OSError, TypeError):
                pass  # Caching is an optimization, not a requirement.

        return reading

    def serve(reading: UsageReading | None) -> UsageReading | None:
        """The reading kept in the file, when it is within its time and its window."""
        if reading is None or ttl <= timedelta(0) or now - reading.observed_at >= ttl:
            return None
        if _past_reset(reading, now):
            return None
        telemetry.count("abk.usage.cache", 1, event="hit")
        record_call(
            calls_file,
            UsageCall(
                account=claude_account.account_key(),
                at=now,
                caller=caller,
                outcome="cache",
                age_seconds=int((now - reading.observed_at).total_seconds()),
            ),
        )
        return reading

    if (hit := serve(kept)) is not None:
        return hit
    if kept is not None:
        telemetry.count("abk.usage.cache", 1, event="expiry")

    # One process refreshes: a process that finds the lock held serves the last good reading.
    with try_file_lock(cache_path.with_name(cache_path.name + ".lock")) as taken:
        if not taken:
            telemetry.count("abk.usage.cache", 1, event="wait")
            # The call is being made by the holder, so the fallback age, which covers a
            # failed call, does not apply: serve the kept reading while its window stands.
            return kept if kept is not None and not _past_reset(kept, now) else None
        # Another process may have refreshed while this one waited to ask.
        cached = _load_cache(cache_path)
        kept = _kept_reading(cached)
        if (hit := serve(kept)) is not None:
            return hit
        return _refresh_under_lock()


def read_cached_usage(path: Path | None = None) -> UsageReading | None:
    """Read Claude Code's own cache in its state file (the account's, else ~/.claude.json)."""
    path = path or _state_file()

    try:
        raw = json.loads(path.read_text())
        cached = raw["cachedUsageUtilization"]
        utilization = cached["utilization"]
        session = utilization["five_hour"]
        weekly = utilization["seven_day"]

        return UsageReading(
            session_pct=int(float(session["utilization"])),
            weekly_pct=int(float(weekly["utilization"])),
            resets_at=_reset_time(session.get("resets_at")),
            weekly_resets_at=_reset_time(weekly.get("resets_at")),
            observed_at=datetime.fromtimestamp(cached["fetchedAtMs"] / 1000, tz=UTC),
            source="claude.json",
            # This cache carries no credits state. Absence is not "disabled",
            # so the credits rule simply doesn't fire on a fallback reading —
            # the threshold check is what protects the account there.
            credits_enabled=False,
            credits_used_dollars=0.0,
            spend_limit_reached=False,
        )
    except (OSError, ValueError, KeyError, TypeError):
        return None


def forget_logged_failures() -> None:
    """Start a tick: a failure's cause is logged again the first time it recurs."""
    _logged_failures.clear()


def rate_limit_note(cache_path: Path | None = None) -> str | None:
    """Words for an endpoint cool-down in force and when it ends, else None."""
    until = _cooldown_until(_load_cache(cache_path or _cache_file()))
    if until is None or until <= datetime.now(UTC):
        return None
    return f"rate limited until {_hhmm(until)}"


_caller: ContextVar[str] = ContextVar("usage_caller", default="guard")


@contextmanager
def reading_as(caller: str) -> Iterator[None]:
    """Name who asks for the readings taken inside the block, in the call record."""
    token = _caller.set(caller)
    try:
        yield
    finally:
        _caller.reset(token)


_starting: ContextVar[str | None] = ContextVar("usage_starting", default=None)


@contextmanager
def starting(unit: str) -> Iterator[None]:
    """Name the unit (or track) a start is asked for inside the block, so an allowance on an
    estimate is kept under its id and counted once. An ask outside one starts nothing."""
    token = _starting.set(unit)
    try:
        yield
    finally:
        _starting.reset(token)


def _noted(reading: UsageReading | None) -> UsageReading | None:
    """A reading that is not live, labelled with the rate limit in force, so the reason a start
    was refused names it and when the next call will be made."""
    note = rate_limit_note()
    if reading is not None and note is not None and not reading.is_live:
        return reading.model_copy(update={"source": f"{reading.source} ({note})"})
    return reading


def _unspent(reading: UsageReading | None) -> UsageReading | None:
    """The reading, unless a window it describes has reset since it was taken."""
    if reading is None or _past_reset(reading, datetime.now(UTC)):
        return None
    return reading


def current_usage() -> UsageReading | None:
    """The best reading available: live if possible, else the local cache."""
    return _noted(read_live_usage() or _unspent(read_cached_usage()))


def _fresh_claude_block(held: UsageReading | None) -> UsageReading | None:
    """The block in Claude Code's own cache, when it is fresh enough to decide from: younger than
    `usage_claude_cache_minutes` (at most `MAX_ANCHOR_AGE`), no window reset, and fresher than the
    reading `held` whatever its age (a tie is the guard's). Off, it does not read the file."""
    minutes = claude_limits().usage_claude_cache_minutes
    if minutes <= 0:
        return None
    block = _unspent(read_cached_usage())
    if block is None or block.age >= min(timedelta(minutes=minutes), MAX_ANCHOR_AGE):
        return None
    if (
        held is not None
        and not _past_reset(held, datetime.now(UTC))
        and block.observed_at <= held.observed_at
    ):
        return None
    return block


def _labelled(decision: Decision, reading: UsageReading) -> Decision:
    """The reason with the source and the reading's age in a parenthesis of its own."""
    ending = f", {reading.source})"
    if not decision.reason.endswith(ending):
        return decision
    age = int(reading.age.total_seconds() // 60)
    reason = f"{decision.reason.removesuffix(ending)}) ({reading.source}, {age}m old)"
    return decision.model_copy(update={"reason": reason})


def held_usage() -> UsageReading | None:
    """The reading held now, from the cache file or Claude Code's own: no call is made."""
    kept = _unspent(_kept_reading(_load_cache(_cache_file())))
    block = _fresh_claude_block(kept)
    return _noted(block or kept or _unspent(read_cached_usage()))


def next_call_at(calls_file: Path, *, now: datetime) -> datetime | None:
    """When the endpoint may next be asked, or None when it may be asked now: no sooner than
    the cache interval after the last call."""
    asked = [c.at for c in read_calls(calls_file) if is_endpoint_call(c)]
    if not asked:
        return None
    allowed = max(asked) + current_cache_interval(calls_file).kept
    return allowed if allowed > now else None


def refreshed_usage() -> UsageReading | None:
    """A fresh reading when the interval allows a call, else the one held."""
    calls_file = _cache_file().parent / CALLS_NAME
    kept = _unspent(_kept_reading(_load_cache(_cache_file())))
    if (block := _fresh_claude_block(kept)) is not None:
        return _noted(block)
    if next_call_at(calls_file, now=datetime.now(UTC)) is None:
        return current_usage()
    return held_usage()


# The shapes a refusal has been seen to arrive in. Not a contract — Claude
# Code's error text is not documented as one — so this matches several
# phrasings rather than one, and the cost of a false positive (a tick pauses
# and retries later) is far below a false negative (an unattended run retries
# a refusal every five minutes all night).
RATE_LIMIT_MARKERS = (
    "usage limit reached",
    "rate limit",
    "rate_limit_error",
    "limit reached",
)

# A status code is a whole number: not the middle of a hash or a millisecond count.
HTTP_429 = re.compile(r"(?<![0-9A-Za-z])429(?![0-9A-Za-z])")

# "Claude AI usage limit reached|1919763200" — an epoch seconds reset.
RESET_EPOCH = re.compile(r"limit reached\|(\d{10,})")


# What the agent runtime raises, under the names the pipeline catches them by.
# A killed run says nothing about the work, so it must not fail the unit: it
# is left `running`, and the next tick resumes it from its thread. A refusal means the
# unit is fine and the account is out of room, so the pipeline pauses rather
# than marking real work failed and dropping it from the plan.
Interrupted = AgentInterrupted
RateLimited = AgentRateLimited


def rate_limit_reset(text: str) -> datetime | None | Literal[False]:
    """Whether `text` is a refusal, and when it lifts.

    Three answers, deliberately: a `datetime` when the message says when,
    `None` when it is a refusal that does not say (the live reading supplies
    the time instead), and `False` when it is not a refusal at all. A plain
    `None` for both cases would make "no timestamp" read as "not rate
    limited", which is the one mistake that matters here.
    """
    lowered = text.lower()
    if not (any(marker in lowered for marker in RATE_LIMIT_MARKERS) or HTTP_429.search(lowered)):
        return False

    match = RESET_EPOCH.search(lowered)
    return datetime.fromtimestamp(int(match.group(1)), UTC) if match else None


def may_start_unit(reading: UsageReading | None, *, trust_age: bool = False) -> Decision:
    """Decide whether a new unit may start now.

    Units already running are not affected: this gates starting work, so
    nothing is ever left half-committed or unpushed by a pause. The headroom
    above the threshold is what pays for them finishing.

    **The threshold is the operative limit.** It is a window's pause percent,
    rising towards its ceiling as that window nears its reset when the two
    differ (`threshold_at`), and each window is judged against its own. The
    credits checks below are backstops for the case where something has already
    gone wrong; they can only ever stop work earlier, never permit more of it.
    Available credits are the user's reserve, not headroom for the pipeline,
    so a healthy credit balance does not raise a ceiling.

    A reading from a cache is refused as stale past `MAX_ANCHOR_AGE`, unless `trust_age`
    says the caller has shown the reading's age cannot change the answer.
    """
    now = datetime.now(UTC)

    if reading is None:
        note = rate_limit_note()
        return Decision(
            may_start=False,
            reason=f"usage is unknown: neither the usage endpoint nor {_state_file()} could be read"
            + (f" (the usage endpoint is {note})" if note else ""),
            resume_at=now + UNKNOWN_RETRY,
        )

    limits = Limits.configured()

    # Backstops first, so they can only make the answer stricter. Past the
    # plan limit the next call is billed to credits, which is never something
    # to start unattended — but note that the threshold check further down is
    # what should have stopped work long before this point.
    if reading.spend_limit_reached:
        return Decision(
            may_start=False,
            reason=(
                "the plan limit is reached and credits are paying "
                f"(${reading.credits_used_dollars:.2f} used)"
            ),
            resume_at=_resume_after(reading),
        )

    if reading.credits_enabled and max(reading.session_pct, reading.weekly_pct) >= 100:
        return Decision(
            may_start=False,
            reason="a usage window is full and credits are enabled, so further work costs money",
            resume_at=_resume_after(reading),
        )

    # A live reading was just taken, so only a reading from a cache can be stale.
    if not trust_age and not reading.is_live and reading.age > MAX_ANCHOR_AGE:
        return Decision(
            may_start=False,
            reason=(
                f"usage reading is stale ({int(reading.age.total_seconds() // 60)}m old, "
                f"from {reading.source}); headless runs don't refresh it"
            ),
            resume_at=now + _stale_retry(),
        )

    for window in reading.windows:
        threshold = threshold_at(window, now=now, limits=limits)
        if window.used_pct >= threshold:
            return Decision(
                may_start=False,
                reason=(
                    f"{window.name} usage at {window.used_pct}% "
                    f"({_threshold_note(window, threshold, limits)}, {reading.source})"
                ),
                resume_at=_resume_to(window, now=now, limits=limits),
            )

    return Decision(
        may_start=True,
        reason=(
            f"session {reading.session_pct}%, weekly {reading.weekly_pct}% "
            f"({_thresholds_note(reading, now=now, limits=limits)}, {reading.source})"
        ),
    )


def _headroom_holds(held: UsageReading, calls_file: Path, now: datetime) -> bool:
    """Whether no window could have climbed to its threshold since the reading was taken."""
    limits = Limits.configured()
    climb = claude_limits()
    calls = read_calls(calls_file)
    minutes = (now - held.observed_at).total_seconds() / 60
    return all(
        window.used_pct
        + most_added(
            calls,
            window.name,
            minutes=minutes,
            floor=climb.usage_climb_floor,
            margin=climb.usage_climb_margin_pct,
            min_gap=timedelta(minutes=climb.usage_cache_minutes),
        )
        < threshold_at(window, now=now, limits=limits)
        for window in held.windows
    )


class WindowEstimate(Frozen):
    """One window's usage now, estimated from the reading kept: the figure read and the
    points the reading cannot have seen, judged against the window's threshold."""

    name: Literal["session", "weekly"]
    read_pct: int
    spent_pct: float
    threshold: int
    margin: int

    @property
    def estimate(self) -> float:
        return self.read_pct + self.spent_pct

    @property
    def ample(self) -> bool:
        return self.estimate + self.margin < self.threshold

    @property
    def text(self) -> str:
        shown = (
            f"{self.name} ~{round(self.estimate)}% estimated "
            f"({self.read_pct}% read + {round(self.spent_pct)}% spent)"
        )
        if self.ample:
            return f"{shown} under {self.threshold}%"
        return f"{shown} is not {self.margin} points under {self.threshold}%"


def estimate_usage(
    held: UsageReading,
    *,
    now: datetime,
    limits: Limits,
    margin: int,
    allowances: dict[str, int],
    units_since: Callable[[datetime], int],
    climb: Callable[[Literal["session", "weekly"], float], float],
) -> list[WindowEstimate]:
    """Each window's estimate now, session first, from the reading `held`.

    A window that has not reset is its figure read plus its allowance for each unit that has
    spent or started since the reading. One that has reset since starts from zero at the
    reset, plus `climb` (the most it could have added in the minutes since) and its allowance
    for each unit since the reset: a reading says nothing about a window it no longer
    describes. `units_since` counts the units that spent or started since a time.
    """
    estimates = []
    for window in reversed(held.windows):
        reset = window.resets_at is not None and held.observed_at < window.resets_at <= now
        if window.resets_at is not None and reset:
            since = window.resets_at
            added = climb(window.name, (now - since).total_seconds() / 60)
            judged = window.model_copy(update={"used_pct": 0, "resets_at": None})
            read = 0
        else:
            since, added, judged, read = held.observed_at, 0.0, window, window.used_pct
        estimates.append(
            WindowEstimate(
                name=window.name,
                read_pct=read,
                spent_pct=added + allowances[window.name] * units_since(since),
                threshold=threshold_at(judged, now=now, limits=limits),
                margin=margin,
            )
        )
    return estimates


def _estimate_text(held: UsageReading, estimates: list[WindowEstimate], now: datetime) -> str:
    age = int((now - held.observed_at).total_seconds() // 60)
    return f"usage: reading {age}m old, " + ", ".join(each.text for each in estimates)


def _admitted(cached: dict) -> list[str]:
    units = cached.get("estimate_units")
    return [u for u in units if isinstance(u, str)] if isinstance(units, list) else []


def _estimates(
    held: UsageReading, cached: dict, cache_path: Path, now: datetime
) -> list[WindowEstimate]:
    """The estimate of both windows from the reading kept, the ledger beside the cache file
    and the units admitted on an estimate since."""
    limits = claude_limits()
    calls = read_calls(cache_path.parent / CALLS_NAME)
    kept = read_allowances(cache_path.parent / ALLOWANCES_NAME)
    admitted = set(_admitted(cached))
    spent = spend_times(read_ledger(cache_path.parent / LEDGER_NAME))

    def units_since(since: datetime) -> int:
        return len(admitted | {unit for at, unit in spent if at >= since})

    def climb(window: Literal["session", "weekly"], minutes: float) -> float:
        return most_added(
            calls,
            window,
            minutes=minutes,
            floor=limits.usage_climb_floor,
            margin=limits.usage_climb_margin_pct,
            min_gap=timedelta(minutes=limits.usage_cache_minutes),
        )

    return estimate_usage(
        held,
        now=now,
        limits=Limits.configured(),
        margin=limits.usage_headroom_margin_pct,
        allowances={window: allowance_for(window, kept.get(window), limits) for window in WINDOWS},
        units_since=units_since,
        climb=climb,
    )


def _estimable(held: UsageReading | None) -> UsageReading | None:
    """The reading an estimate may rest on: one kept by the guard that is not at the plan limit
    and, with credits enabled, has no window full."""
    if held is None or held.spend_limit_reached:
        return None
    if held.credits_enabled and max(held.session_pct, held.weekly_pct) >= 100:
        return None
    return held


def _decide_on_estimate(
    held: UsageReading,
    cached: dict,
    cache_path: Path,
    *,
    now: datetime,
    unit: str | None,
    next_call: datetime | None,
) -> Decision:
    """Whether a unit may start when the endpoint cannot be asked: the estimate, then the cap.

    A refusal carries the estimate's text and, for the cap, the time the endpoint may next be
    asked. An allowance is recorded in the cache file under its lock."""
    estimates = _estimates(held, cached, cache_path, now)
    text = _estimate_text(held, estimates, now)
    if not all(each.ample for each in estimates):
        return Decision(may_start=False, reason=text, resume_at=next_call)
    admitted = _admitted(cached)
    cap = claude_limits().usage_estimate_max_starts
    if (unit is None or unit not in admitted) and len(admitted) >= cap:
        return Decision(
            may_start=False,
            reason=(
                f"{text}; {len(admitted)} starts have been made on an estimate "
                f"(at most {cap} for one reading)"
            ),
            resume_at=next_call or now + _stale_retry(),
        )
    if unit is not None:
        _record_admitted(cache_path, held, unit)
    return Decision(may_start=True, reason=f"{text}, allowing starts", resets_at=held.resets_at)


def _record_admitted(cache_path: Path, held: UsageReading, unit: str) -> None:
    """Keep `unit` with the reading as started on an estimate, unless a good read has replaced
    the reading meanwhile."""
    try:
        with file_lock(cache_path.with_name(cache_path.name + ".lock")):
            cached = _load_cache(cache_path)
            kept = _kept_reading(cached)
            if kept is None or kept.observed_at != held.observed_at:
                return
            admitted = _admitted(cached)
            if unit not in admitted:
                _write_cache(cache_path, {**cached, "estimate_units": [*admitted, unit]})
    except (OSError, TypeError):
        pass


def held_estimate_line() -> str | None:
    """The estimate line from the reading held, for `abk status`: no call is made. Only when the
    reading is older than the time a reading is kept and the endpoint cannot be asked."""
    now = datetime.now(UTC)
    cache_path = _cache_file()
    calls_file = cache_path.parent / CALLS_NAME
    cached = _load_cache(cache_path)
    held = _estimable(_kept_reading(cached))
    if held is None or now - held.observed_at < current_cache_interval(calls_file).kept:
        return None
    if not _cooling(cached, now) and next_call_at(calls_file, now=now) is None:
        return None
    estimates = _estimates(held, cached, cache_path, now)
    text = _estimate_text(held, estimates, now)
    return text + (", allowing starts" if all(each.ample for each in estimates) else "")


def _too_soon(allowed: datetime, now: datetime) -> Decision:
    return Decision(
        may_start=False,
        reason=(
            "usage must be read again but the endpoint was asked too recently: "
            f"the minimum interval allows the next call at {_hhmm(allowed)} "
            f"({int((allowed - now).total_seconds() // 60) + 1}m)"
        ),
        resume_at=allowed,
    )


def decide_start(
    *,
    read: Callable[[], UsageReading | None] | None = None,
    decide: Callable[..., Decision] | None = None,
    unit: str | None = None,
) -> Decision:
    """Whether a unit may start now, asking the endpoint only when a fresh reading
    could change the answer and the minimum interval allows a call.

    Usage only rises within a window, so a refusal on a reading of a window that has not
    reset stands, and an allowance stands while the most the usage could have added since
    the reading (`most_added`) leaves it under the threshold. A reading of a window that
    has reset, or none, needs a fresh one; so does anything closer to the threshold.
    `read` and `decide` stand for `current_usage` and `may_start_unit` where a fresh
    reading is taken, for a caller that has its own.
    """
    unit = unit or _starting.get()
    read = read or current_usage
    judge = decide or may_start_unit

    def carrying(decision: Decision, reading: UsageReading | None) -> Decision:
        if decision.resets_at is None and reading is not None:
            return decision.model_copy(update={"resets_at": reading.resets_at})
        return decision

    def on_estimate(
        base: UsageReading, refused: Decision, *, next_call: datetime | None
    ) -> Decision:
        """The start allowed on an estimate, or the refusal with the estimate's text added."""
        later = datetime.now(UTC)
        estimated = _decide_on_estimate(
            base, _load_cache(cache_path), cache_path, now=later, unit=unit, next_call=next_call
        )
        if estimated.may_start:
            return estimated
        return refused.model_copy(
            update={
                "reason": f"{refused.reason}; {estimated.reason}",
                "resume_at": refused.resume_at or estimated.resume_at,
            }
        )

    def fresh() -> Decision:
        reading = read()
        decision = carrying(judge(reading), reading)
        unusable = reading is None or (not reading.is_live and reading.age > MAX_ANCHOR_AGE)
        base = _estimable(held)
        if decision.may_start or not unusable or base is None:
            return decision
        # No reading, or one too stale to use: the reading kept may still say there is room.
        return on_estimate(base, decision, next_call=next_call_at(calls_file, now=now))

    now = datetime.now(UTC)
    cache_path = _cache_file()
    calls_file = cache_path.parent / CALLS_NAME
    held = _kept_reading(_load_cache(cache_path))
    if (block := _fresh_claude_block(held)) is not None:
        # A reading of Claude Code's own: it settles the decision without a call, even inside the
        # minimum interval, and is written nowhere.
        record_call(
            calls_file,
            UsageCall(
                account=claude_account.account_key(),
                at=now,
                caller=_caller.get(),
                outcome=CLAUDE_JSON,
                age_seconds=int(block.age.total_seconds()),
            ),
        )
        return _labelled(carrying(judge(block, trust_age=True), block), block)
    if held is not None and not _past_reset(held, now):
        decision = carrying(judge(held, trust_age=True), held)
        if not decision.may_start or _headroom_holds(held, calls_file, now):
            # Answered from the reading held, as a cache hit is, so the record's share is true.
            record_call(
                calls_file,
                UsageCall(
                    account=claude_account.account_key(),
                    at=now,
                    caller=_caller.get(),
                    outcome=CACHE,
                    age_seconds=int((now - held.observed_at).total_seconds()),
                ),
            )
            return decision
        if now - held.observed_at < current_cache_interval(calls_file).kept:
            return fresh()
    allowed = next_call_at(calls_file, now=now)
    if allowed is not None:
        soon = _too_soon(allowed, now)
        base = _estimable(held)
        return soon if base is None else on_estimate(base, soon, next_call=allowed)
    return fresh()


def _stale_retry() -> timedelta:
    return timedelta(minutes=claude_limits().usage_stale_retry_minutes)


def _threshold_note(window: Window, threshold: int, limits: Limits) -> str:
    """The threshold, and — while it is moving — what it is moving towards."""
    band = limits.band(window)
    if not band.ramps or threshold >= band.ceiling_pct or window.resets_at is None:
        return f"threshold {threshold}%"
    if threshold > band.pause_pct:
        return (
            f"threshold {threshold}%, ramping to {band.ceiling_pct}% by {_hhmm(window.resets_at)}"
        )
    return f"threshold {threshold}%"


def _thresholds_note(reading: UsageReading, *, now: datetime, limits: Limits) -> str:
    parts = [
        f"{window.name} {threshold_at(window, now=now, limits=limits)}%"
        for window in reversed(reading.windows)
    ]
    return "thresholds " + ", ".join(parts)


def _hhmm(moment: datetime) -> str:
    return f"{moment.astimezone():%m-%d %H:%M}"


def _resume_to(window: Window, *, now: datetime, limits: Limits) -> datetime:
    """When to look again after a window's threshold refused a unit.

    The ramp may clear the current usage before the reset does; if it never
    will, the reset is the answer. Either way the wait is capped, so a weekly
    window that resets days out doesn't put the pipeline to sleep for days.
    """
    relief = relief_at(window, now=now, limits=limits)
    if relief is None:
        reset = window.resets_at
        relief = reset if reset and reset > now else now + UNKNOWN_RETRY
    return min(relief, now + MAX_SCHEDULED_PAUSE)


class GateResult(Frozen):
    """What one split's gate said: usable, held or unknown, with the figures behind it."""

    state: Literal["usable", "held", "unknown"]
    reason: str = ""
    used_amount: Decimal | None = None
    used_pct: int | None = None
    window_end: datetime | None = None
    threshold: int | None = None
    # When a held result stops standing without a later reading: the window's end,
    # or one cache time on for a command.
    until: datetime | None = None


def provider_decision(
    reading: ProviderReading,
    *,
    limits: ProviderLimitsConfig,
    now: datetime,
    standing: bool = False,
) -> GateResult:
    """Whether a provider's month leaves room, by the threshold the Claude Code windows use."""
    raise NotImplementedError


def gate_result(
    split: str,
    gate: GateConfig,
    *,
    now: datetime,
    state_dir: Path,
    root: Path,
    standing: bool = False,
    refresh: bool = False,
    read: Callable[[], object] | None = None,
    run: Run = subprocess.run,
) -> GateResult:
    """One split's gate evaluated from its configuration, through the per-split cache in
    `<state_dir>/gate-usage.json` unless `refresh`."""
    raise NotImplementedError
