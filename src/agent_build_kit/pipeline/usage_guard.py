"""Whether there is room in the Claude usage window to start another unit.

The account is on a subscription, so the constraint isn't dollars — it's the
plan's usage window, shared with the user's own interactive sessions. Credits
are enabled past the plan limit, which means running to 100% spends real money
instead of stopping. So unattended work stops starting new units at
the pause percent of the window that is full (`usage_pause_pct`, 70 by default,
in the `session` or `weekly` section of `runtimes.claude_code.usage_limits`) and
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
from collections.abc import Callable, Collection, Iterator
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
    WindowLimits,
    active,
    active_root,
)
from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.file_lock import atomic_write_text, file_lock, try_file_lock
from agent_build_kit.pipeline.pause import UNKNOWN_RETRY
from agent_build_kit.pipeline.usage_allowances import (
    SESSION_WINDOW,
    WEEKLY_WINDOW,
    allowance_for,
    allowances_path,
    cost_basis_in_force,
    of_account,
    read_allowances,
)
from agent_build_kit.pipeline.usage_calls import (
    CACHE,
    CLAUDE_JSON,
    CacheInterval,
    UsageCall,
    cache_interval,
    calls_path,
    is_endpoint_call,
    most_added,
    rate_limit_headers,
    read_calls,
    record_call,
)
from agent_build_kit.pipeline.usage_forecast_ask import Ask, AskForecast, forecast_ask
from agent_build_kit.pipeline.usage_forecast_record import (
    FORECASTS_NAME,
    ForecastRow,
    StepRow,
    WindowForecast,
    read_record,
    record_admission,
)
from agent_build_kit.pipeline.usage_forecast_reservations import TimerReading, read_timers
from agent_build_kit.pipeline.usage_forecast_running import running_remainders
from agent_build_kit.pipeline.usage_forecast_status import WindowFacts, forecast_line
from agent_build_kit.pipeline.usage_forecast_unit import forecast_unit
from agent_build_kit.pipeline.usage_ledger import LEDGER_NAME, UsageRecord, read_ledger, spend_costs
from agent_build_kit.pipeline.verdict import ReviewTier
from agent_build_kit.pipeline.verdict_record import VERDICTS, VerdictEntry, recorded_verdicts
from agent_build_kit.runtimes.base import AgentInterrupted, AgentRateLimited, Run
from agent_build_kit.runtimes.providers import (
    GateCommandResult,
    ProviderReading,
    ProviderUnknown,
    run_gate_command,
)
from agent_build_kit.runtimes.providers import read_usage as read_provider_usage
from agent_build_kit.settings import settings

# The one window a provider has, and the file its readings are kept in, per split.
PROVIDER_WINDOW = "billing"
GATE_USAGE_NAME = "gate-usage.json"
# What an unknown gate result says when nothing was asked for it.
NOT_READ_REASON = "not read yet; `abk status --refresh` reads it"

USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
OAUTH_BETA_HEADER = "oauth-2025-04-20"

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

    name: str
    used_pct: int
    resets_at: datetime | None
    length: timedelta


class ClaudeWindow(Window):
    """A window of the Claude Code subscription, which only the two have."""

    name: Literal["session", "weekly"]  # pyrefly: ignore[bad-override]


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
    def windows(self) -> tuple[ClaudeWindow, ...]:
        """Both windows, weekly first — the order `may_start_unit` reports
        them in, so the longer window is named when both are over."""
        return (
            ClaudeWindow(
                name="weekly",
                used_pct=self.weekly_pct,
                resets_at=self.weekly_resets_at,
                length=WEEKLY_WINDOW,
            ),
            ClaudeWindow(
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
    # What the decision was made on, for the admission record: the reading's source and age,
    # the threshold and ramp value used, and whether it was a start on an estimate (and how
    # many starts have been made on that estimate).
    source: str = ""
    age_seconds: float | None = None
    threshold: float | None = None
    ramp: float | None = None
    estimate: bool = False
    estimate_starts: int = 0

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


def read_oauth_token(
    path: Path | None = None, *, account: claude_account.Account | None = None
) -> str | None:
    """Find Claude Code's stored OAuth token.

    Read-only, and the value is never logged or written anywhere by this
    module — it goes straight into the Authorization header.
    """
    from_env = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN")
    if from_env:
        return from_env

    try:
        raw = json.loads(
            (path or claude_account.credentials_path(account or account_in_force())).read_text()
        )
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


def _band(window: WindowLimits) -> Band:
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


def token_expired(
    path: Path | None = None,
    *,
    account: claude_account.Account | None = None,
    now: datetime | None = None,
) -> bool:
    """Whether the saved OAuth access token has passed its `expiresAt`.

    False when that cannot be read: the refresh below is only for the state it
    is known to fix, not a general retry.
    """
    expires = token_expires_at(path, account=account)
    if expires is None:
        return False
    return datetime.fromtimestamp(expires / 1000, tz=UTC) <= (now or datetime.now(UTC))


def token_expires_at(
    path: Path | None = None, *, account: claude_account.Account | None = None
) -> int | float | None:
    """The `expiresAt` (milliseconds) in the account's credentials file, else None. The token
    itself is not read."""
    path = path or claude_account.credentials_path(account or account_in_force())
    try:
        raw = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    oauth = raw.get("claudeAiOauth", raw) if isinstance(raw, dict) else {}
    expires = oauth.get("expiresAt") if isinstance(oauth, dict) else None
    return expires if isinstance(expires, (int, float)) else None


def refresh_login(account: claude_account.Account | None = None) -> None:
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

    The call is made under the account in force (`on_account`), so the token it
    refreshes is the one the usage read uses.
    """
    from agent_build_kit.runtimes import claude_code

    claude_code.refresh_login(account or account_in_force())


def account_in_force() -> claude_account.Account:
    """The account in force (`on_account`), else the default account."""
    return _account.get() or claude_account.Account.default()


def claude_limits() -> ClaudeLimitsConfig:
    """The limits of the account in force (`on_account`), else the runtime's."""
    if (account := _account.get()) is not None:
        return account.usage_limits
    return active().runtimes.get(CLAUDE_CODE, RuntimeConfig()).usage_limits


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
    return _of_account(state / "usage-cache.json")


def _of_account(path: Path) -> Path:
    """`path` for the account in force: see `claude_account.file_for`."""
    return claude_account.file_for(path, account_in_force())


def _calls_file(cache_path: Path) -> Path:
    return calls_path(cache_path.parent, account_in_force())


def _load_cache(path: Path) -> dict:
    try:
        cached = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    if not isinstance(cached, dict) or cached.get("account") != claude_account.account_key(
        account_in_force()
    ):
        # A reading, cool-down or fallback of another account (or of none while one is in use,
        # or of one while none is) is never served; the next write replaces it.
        return {}
    return cached


def _write_cache(path: Path, body: dict) -> None:
    """Write the cache file whole: a reader outside the lock never sees half of it. The
    account is recorded only when one is set."""
    if (account := claude_account.account_key(account_in_force())) is not None:
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
    expired: Callable[[claude_account.Account], bool] | None = None,
    refresh: Callable[[claude_account.Account], None] | None = None,
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
    account = account_in_force()
    cache_path = cache_path or _cache_file()
    calls_file = _calls_file(cache_path)
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
        token = token or read_oauth_token(account=account)
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
                        account=claude_account.account_key(account),
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

        def failed(error: Exception, *, refreshed: bool = False) -> UsageReading | None:
            if isinstance(error, urllib.error.HTTPError):
                cause = f"HTTP {error.code}"
                if error.code == 401 and refreshed:
                    # The login is rejected, not the usage unknown: kept beside the reading so
                    # status, doctor and the start decision say so until a read succeeds or the
                    # credentials change (a new sign-in), told by the `expiresAt` they rejected.
                    try:
                        cache_path.parent.mkdir(parents=True, exist_ok=True)
                        rejected = {"expires_at": token_expires_at(account=account)}
                        _write_cache(cache_path, {**cached, "login_rejected": rejected})
                    except (OSError, TypeError):
                        pass
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
            if given is None and (expired or (lambda a: token_expired(account=a)))(account):
                (refresh or refresh_login)(account)
                fresh = read_oauth_token(account=account)
                if not fresh or fresh == token:
                    label = account.label or "default"
                    if (unchanged := f"unchanged token of {label}") not in _logged_failures:
                        _logged_failures.add(unchanged)
                        log.warning(
                            "account %s: the login refresh left the saved token as it was", label
                        )
                    return failed(error, refreshed=True)
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
                return failed(again, refreshed=retry_with != token)

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
                account=claude_account.account_key(account),
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
    path = path or claude_account.state_file(account_in_force())

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


def rejected_login_note(account: claude_account.Account | None = None) -> str | None:
    """Words for a login the usage endpoint rejected after a refresh, with the command to sign
    in again, else None. Kept in the account's cache file until a read succeeds or the
    account's credentials carry a different `expiresAt` than the ones rejected."""
    with on_account(account):
        rejected = _load_cache(_cache_file()).get("login_rejected")
        if not rejected:
            return None
        rejected_expiry = rejected.get("expires_at") if isinstance(rejected, dict) else None
        if token_expires_at() != rejected_expiry:
            return None
        from agent_build_kit.runtimes import claude_code

        return claude_code.rejected_login_line(account_in_force())


def rate_limit_note(cache_path: Path | None = None) -> str | None:
    """Words for an endpoint cool-down in force and when it ends, else None."""
    until = _cooldown_until(_load_cache(cache_path or _cache_file()))
    if until is None or until <= datetime.now(UTC):
        return None
    return f"rate limited until {_hhmm(until)}"


_account: ContextVar[claude_account.Account | None] = ContextVar("usage_account", default=None)


@contextmanager
def on_account(account: claude_account.Account | None) -> Iterator[None]:
    """Run the readings and decisions inside the block for `account`: its credentials, state
    file, cache, call record and limits. None leaves the account in force as it is."""
    if account is None:
        yield
        return
    token = _account.set(account)
    try:
        yield
    finally:
        _account.reset(token)


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
_facts: ContextVar[Ask | None] = ContextVar("usage_starting_facts", default=None)


@contextmanager
def starting(
    unit: str,
    *,
    review_tier: ReviewTier | None = None,
    estimated_lines: int | None = None,
    step: str | None = None,
    step_round: int | None = None,
) -> Iterator[None]:
    """Name the unit (or track) a start is asked for inside the block, so an allowance on an
    estimate is kept under its id and counted once, and the unit's review tier and estimated
    lines and the step and round it is for, which its forecast is made from. An ask outside one
    starts nothing."""
    token = _starting.set(unit)
    facts = _facts.set(
        Ask(unit=unit, tier=review_tier, lines=estimated_lines, step=step, step_round=step_round)
    )
    try:
        yield
    finally:
        _facts.reset(facts)
        _starting.reset(token)


def ask_before_call(
    unit: str,
    may_start: Callable[[], tuple[bool, str]],
    resume_at: Callable[[], datetime | None],
) -> None:
    """Ask the guard before an agent call of `unit` that no node gates (a conflict resolver's),
    by the decision a unit's agent step asks. A refusal is raised as the model's own rate limit,
    carrying the time the guard expects to allow the call again."""
    with starting(unit):
        allowed, reason = may_start()
    if not allowed:
        raise AgentRateLimited(reason, resets_at=resume_at())


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


def current_usage(account: claude_account.Account | None = None) -> UsageReading | None:
    """The best reading available: live if possible, else the local cache."""
    with on_account(account):
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


def held_usage(account: claude_account.Account | None = None) -> UsageReading | None:
    """The reading held now, from the cache file or Claude Code's own: no call is made."""
    with on_account(account):
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
    calls_file = _calls_file(_cache_file())
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


def _reading_facts(reading: UsageReading) -> dict:
    """The reading's source and age, as a decision records them."""
    return {"source": reading.source, "age_seconds": reading.age.total_seconds()}


def _ramp_of(name: str, limits: Limits) -> int | None:
    """The ceiling the named window's threshold ramps to, or None for a window that does not
    ramp."""
    band = limits.session if name == "session" else limits.weekly
    return band.ceiling_pct if band.ramps else None


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
        rejected = rejected_login_note()
        return Decision(
            may_start=False,
            reason="usage is unknown: neither the usage endpoint nor "
            f"{claude_account.state_file(account_in_force())} could be read"
            + (f" (the usage endpoint is {note})" if note else "")
            + (f"; {rejected}" if rejected else ""),
            resume_at=now + UNKNOWN_RETRY,
        )

    limits = Limits.configured()
    facts = _reading_facts(reading)

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
            **facts,
        )

    if reading.credits_enabled and max(reading.session_pct, reading.weekly_pct) >= 100:
        return Decision(
            may_start=False,
            reason="a usage window is full and credits are enabled, so further work costs money",
            resume_at=_resume_after(reading),
            **facts,
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
            **facts,
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
                threshold=threshold,
                ramp=_ramp_of(window.name, limits),
                **facts,
            )

    # The window nearest its threshold is the one that came closest to refusing.
    thresholds = {each.name: threshold_at(each, now=now, limits=limits) for each in reading.windows}
    nearest = min(
        reading.windows, key=lambda each: thresholds[each.name] - each.used_pct, default=None
    )
    return Decision(
        may_start=True,
        reason=(
            f"session {reading.session_pct}%, weekly {reading.weekly_pct}% "
            f"({_thresholds_note(reading, now=now, limits=limits)}, {reading.source})"
        ),
        threshold=thresholds[nearest.name] if nearest is not None else None,
        ramp=_ramp_of(nearest.name, limits) if nearest is not None else None,
        **facts,
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
    cost_usd: float | None = None  # the recorded cost counted; None on the units basis
    unrecorded: int = 0  # units counted at the flat allowance for want of a cost
    ahead: AskForecast | None = None  # what the ask is forecast to need, when it is forecast
    estimated: bool = True  # False for a reading just taken or kept: nothing is added to it

    @property
    def estimate(self) -> float:
        return self.read_pct + self.spent_pct

    @property
    def forecast(self) -> float:
        return self.ahead.points if self.ahead is not None else 0.0

    @property
    def ample(self) -> bool:
        return self.estimate + self.forecast + self.margin < self.threshold

    @property
    def text(self) -> str:
        counted = ""
        if self.cost_usd is not None:
            counted = f" from ${self.cost_usd:.2f} recorded"
            if self.unrecorded:
                plural = "unit" if self.unrecorded == 1 else "units"
                counted += f", {self.unrecorded} {plural} not yet recorded"
        if self.estimated:
            shown = (
                f"{self.name} ~{round(self.estimate)}% estimated "
                f"({self.read_pct}% read + {round(self.spent_pct)}% spent{counted})"
            )
        else:
            shown = f"{self.name} {self.read_pct}% read"
        if self.forecast > 0:
            shown += f" + {self.forecast:.1f}% forecast"
        if self.ample:
            return f"{shown} under {self.threshold}%"
        return f"{shown} is not {self.margin} points under {self.threshold}%"


class Spend(Frozen):
    """What the pipeline may have spent in one window since a time: the points, and for a
    window on the cost basis the recorded cost counted and the units counted without one."""

    points: float
    cost_usd: float | None = None
    unrecorded: int = 0


def estimate_usage(
    held: UsageReading,
    *,
    now: datetime,
    limits: Limits,
    margin: int,
    spend: Callable[[Literal["session", "weekly"], datetime, bool], Spend],
    climb: Callable[[Literal["session", "weekly"], float], float],
) -> list[WindowEstimate]:
    """Each window's estimate now, session first, from the reading `held`.

    A window that has not reset is its figure read plus its allowance for each unit that has
    spent or started since the reading. One that has reset since starts from zero at the
    reset, plus `climb` (the most it could have added in the minutes since) and its allowance
    for each unit since the reset: a reading says nothing about a window it no longer
    describes. `spend(window, since, reset)` is what was spent in the window since a time, on
    the window's basis; `reset` says the time is the window's reset, not the reading's.
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
        spent = spend(window.name, since, reset)
        estimates.append(
            WindowEstimate(
                name=window.name,
                read_pct=read,
                spent_pct=added + spent.points,
                threshold=threshold_at(judged, now=now, limits=limits),
                margin=margin,
                cost_usd=spent.cost_usd,
                unrecorded=spent.unrecorded,
            )
        )
    return estimates


def _estimate_text(held: UsageReading, estimates: list[WindowEstimate], now: datetime) -> str:
    age = int((now - held.observed_at).total_seconds() // 60)
    return f"usage: reading {age}m old, " + ", ".join(each.text for each in estimates)


def _forecast_note(estimates: list[WindowEstimate]) -> str:
    """The forecast in words for the first window it is part of the refusal of, with what
    dominates it; nothing when no window is refused with a forecast."""
    for each in estimates:
        if not each.ample and each.ahead is not None and each.forecast > 0:
            return "; " + each.ahead.text(each.name)
    return ""


def _account_ledger(cache_path: Path) -> list[UsageRecord]:
    """The ledger rows of the account in force: only what ran on it spent its windows."""
    account = account_in_force()
    return of_account([], read_ledger(cache_path.parent / LEDGER_NAME), account)[1]


class _ForecastContext(Frozen):
    """What a forecast of any window is made from: each window's facts, the step rows, the
    recorded verdicts and the installed timers."""

    windows: tuple[WindowFacts, ...]
    steps: tuple[StepRow, ...]
    verdicts: dict[str, VerdictEntry]
    timers: TimerReading


def _forecast_context(
    cache_path: Path, resets: dict[str, datetime | None], now: datetime
) -> _ForecastContext:
    """The facts the start decision and `abk status` forecast from, worked out once so the two
    agree: each window of `resets` with its reset (none once past), points a dollar when a cost
    basis is in force and flat allowance."""
    limits = claude_limits()
    account = account_in_force()
    kept = read_allowances(allowances_path(cache_path.parent, account))
    root = active_root()
    # The timers only matter to a window that has a reset ahead.
    open_window = any(at is not None and at > now for at in resets.values())
    timers = (
        read_timers(root)
        if root is not None and open_window
        else TimerReading(read=False, tracks={})
    )
    windows = []
    for name, resets_at in resets.items():
        window: Literal["session", "weekly"] = "session" if name == "session" else "weekly"
        fit = kept.get(window)
        costed = fit is not None and cost_basis_in_force(window, fit, limits)
        windows.append(
            WindowFacts(
                name=name,
                resets_at=resets_at if resets_at is not None and resets_at > now else None,
                points_per_usd=fit.points_per_usd if fit is not None and costed else None,
                flat_allowance=allowance_for(window, fit, limits),
            )
        )
    return _ForecastContext(
        windows=tuple(windows),
        steps=read_record(cache_path.parent / FORECASTS_NAME).steps,
        verdicts=recorded_verdicts(cache_path.parent / VERDICTS),
        timers=timers,
    )


def _ahead(
    ask: Ask,
    cache_path: Path,
    ledger: list[UsageRecord],
    resets: dict[str, datetime | None],
    *,
    now: datetime,
    counted: dict[str, set[str]],
    admitted: bool = False,
) -> dict[str, AskForecast]:
    """The forecast of `ask` for each window of `resets`, from the history, the step rows and the
    installed timers; `counted` are the running units each window's estimate already holds."""
    limits = claude_limits()
    context = _forecast_context(cache_path, resets, now)
    return {
        each.name: forecast_ask(
            ask,
            records=ledger,
            verdicts=context.verdicts,
            steps=context.steps,
            timers=context.timers,
            now=now,
            resets_at=each.resets_at,
            points_per_usd=each.points_per_usd,
            flat_allowance=each.flat_allowance,
            min_runs=limits.usage_forecast_min_runs,
            quantile=limits.usage_forecast_quantile,
            counted=counted.get(each.name, ()),
            admitted=admitted,
        )
        for each in context.windows
    }


def _forecasted(decision: Decision, reading: UsageReading | None, ask: Ask | None) -> Decision:
    """`decision`, when it allows a start, held to the forecast on the reading's own figures: no
    window may be within the margin of its threshold once the forecast is added. It can only
    make an answer stricter."""
    if (
        not decision.may_start
        or reading is None
        or ask is None
        or not ask.forecast
        or not claude_limits().usage_forecast
    ):
        return decision
    now = datetime.now(UTC)
    limits = Limits.configured()
    cache_path = _cache_file()
    ahead = _ahead(
        ask,
        cache_path,
        _account_ledger(cache_path),
        {each.name: each.resets_at for each in reading.windows},
        now=now,
        counted={},
    )
    estimates = [
        WindowEstimate(
            name=each.name,
            read_pct=each.used_pct,
            spent_pct=0.0,
            threshold=threshold_at(each, now=now, limits=limits),
            margin=claude_limits().usage_headroom_margin_pct,
            ahead=ahead[each.name],
            estimated=False,
        )
        for each in reading.windows
    ]
    refused = [e for e in estimates if not e.ample]
    if not refused:
        return decision
    window = next(each for each in reading.windows if each.name == refused[0].name)
    return Decision(
        may_start=False,
        reason=f"usage: {', '.join(e.text for e in estimates)}{_forecast_note(estimates)}",
        resume_at=_resume_to(window, now=now, limits=limits),
        resets_at=reading.resets_at,
        threshold=refused[0].threshold,
        ramp=_ramp_of(refused[0].name, limits),
        **_reading_facts(reading),
    )


def _admitted(cached: dict) -> list[str]:
    units = cached.get("estimate_units")
    return [u for u in units if isinstance(u, str)] if isinstance(units, list) else []


def _estimates(
    held: UsageReading, cached: dict, cache_path: Path, now: datetime, ask: Ask | None = None
) -> list[WindowEstimate]:
    """The estimate of both windows from the reading kept, the ledger beside the cache file
    and the units admitted on an estimate since, and what `ask` is forecast to need when it
    is forecast."""
    limits = claude_limits()
    calls = read_calls(_calls_file(cache_path))
    account = account_in_force()
    kept = read_allowances(allowances_path(cache_path.parent, account))
    admitted = set(_admitted(cached))
    # Only what ran on this account spent its windows.
    ledger = _account_ledger(cache_path)
    counted: dict[str, set[str]] = {}
    rows = spend_costs(ledger)
    steps = read_record(cache_path.parent / FORECASTS_NAME).steps if limits.usage_forecast else ()
    stepped = {step.unit for step in steps}

    def spend(window: Literal["session", "weekly"], since: datetime, reset: bool) -> Spend:
        found = kept.get(window)
        flat = allowance_for(window, found, limits)
        since_rows = [row for row in rows if row.at >= since]
        spent_units = admitted | {row.unit for row in since_rows if row.unit}
        if found is None or not cost_basis_in_force(window, found, limits):
            return Spend(points=float(flat * len(spent_units)))
        costed = {row.unit for row in since_rows if row.unit and row.cost_usd > 0}
        waiting = spent_units - costed
        # A unit with a remainder is counted at what is left of its step, not the flat allowance.
        remainders = running_remainders(
            steps,
            ledger,
            running=waiting & stepped,
            asking=_starting.get(),
            now=now,
            points_per_usd=found.points_per_usd or 0.0,
        ).running
        counted[window] = {r.unit for r in remainders}
        # A unit whose step has no costed history gets no remainder and stays at the allowance.
        unrecorded = len(waiting - {r.unit for r in remainders})
        remainder = sum(r.points for r in remainders)
        cost = sum(row.cost_usd for row in since_rows)
        # After a reset the climb stands for what nobody recorded, so no intercept is added.
        hours = 0.0 if reset else (now - since).total_seconds() / 3600
        points = (
            (found.points_per_usd or 0.0) * cost
            + (found.intercept_per_hour or 0.0) * hours
            + flat * unrecorded
            + remainder
        )
        return Spend(points=points, cost_usd=cost, unrecorded=unrecorded)

    def climb(window: Literal["session", "weekly"], minutes: float) -> float:
        return most_added(
            calls,
            window,
            minutes=minutes,
            floor=limits.usage_climb_floor,
            margin=limits.usage_climb_margin_pct,
            min_gap=timedelta(minutes=limits.usage_cache_minutes),
        )

    estimates = estimate_usage(
        held,
        now=now,
        limits=Limits.configured(),
        margin=limits.usage_headroom_margin_pct,
        spend=spend,
        climb=climb,
    )
    if ask is None or not ask.forecast or not limits.usage_forecast:
        return estimates
    ahead = _ahead(
        ask,
        cache_path,
        ledger,
        {each.name: each.resets_at for each in held.windows},
        now=now,
        counted=counted,
        admitted=ask.unit in admitted,
    )
    return [each.model_copy(update={"ahead": ahead[each.name]}) for each in estimates]


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
    step: str | None = None,
    ask: Ask | None = None,
    next_call: datetime | None,
) -> Decision:
    """Whether a unit may start when the endpoint cannot be asked: the estimate, then the cap.

    A refusal carries the estimate's text and, for the cap, the time the endpoint may next be
    asked. An allowance is recorded in the cache file under its lock."""
    estimates = _estimates(held, cached, cache_path, now, ask)
    text = _estimate_text(held, estimates, now)
    nearest = min(estimates, key=lambda each: each.threshold - each.estimate)
    facts = {
        "source": held.source,
        "age_seconds": (now - held.observed_at).total_seconds(),
        "threshold": nearest.threshold,
        "ramp": _ramp_of(nearest.name, Limits.configured()),
    }
    if not all(each.ample for each in estimates):
        return Decision(
            may_start=False, reason=text + _forecast_note(estimates), resume_at=next_call, **facts
        )
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
            **facts,
        )
    if unit is not None:
        _record_admitted(cache_path, held, unit, step)
    return Decision(
        may_start=True,
        reason=f"{text}, allowing starts",
        resets_at=held.resets_at,
        estimate=True,
        # The starts already made on this estimate, and this unit when one is named. A caller
        # that names none (the round's own ask) adds the unit's place among its starts itself.
        estimate_starts=len(admitted) + (1 if unit is not None and unit not in admitted else 0),
        **facts,
    )


def _record_admitted(
    cache_path: Path, held: UsageReading, unit: str, step: str | None = None
) -> None:
    """Keep `unit` with the reading as started on an estimate, and the step it was admitted
    for under a key of its own, unless a good read has replaced the reading meanwhile."""
    try:
        with file_lock(cache_path.with_name(cache_path.name + ".lock")):
            cached = _load_cache(cache_path)
            kept = _kept_reading(cached)
            if kept is None or kept.observed_at != held.observed_at:
                return
            admitted = _admitted(cached)
            if unit not in admitted:
                kept_steps = cached.get("estimate_steps")
                steps = kept_steps if isinstance(kept_steps, dict) else {}
                added = {"estimate_steps": {**steps, unit: step}} if step else {}
                _write_cache(cache_path, {**cached, "estimate_units": [*admitted, unit], **added})
    except (OSError, TypeError):
        pass


def _held_for_status() -> tuple[UsageReading, dict, Path, datetime] | None:
    """The reading, cache, cache path and time the status lines about a held reading rest on:
    only when the reading is older than the time a reading is kept and the endpoint cannot be
    asked."""
    now = datetime.now(UTC)
    cache_path = _cache_file()
    calls_file = _calls_file(cache_path)
    cached = _load_cache(cache_path)
    held = _estimable(_kept_reading(cached))
    if held is None or now - held.observed_at < current_cache_interval(calls_file).kept:
        return None
    if not _cooling(cached, now) and next_call_at(calls_file, now=now) is None:
        return None
    return held, cached, cache_path, now


def held_estimate_line() -> str | None:
    """The estimate line from the reading held, for `abk status`: no call is made. Only when the
    reading is older than the time a reading is kept and the endpoint cannot be asked."""
    found = _held_for_status()
    if found is None:
        return None
    held, cached, cache_path, now = found
    estimates = _estimates(held, cached, cache_path, now)
    text = _estimate_text(held, estimates, now)
    return text + (", allowing starts" if all(each.ample for each in estimates) else "")


def held_forecast_line(running: Collection[str]) -> str | None:
    """The forecast line beside the estimate line, for `abk status`: no call is made. Nothing
    when the forecast is off or the estimate line is not printed; `running` are the units
    running now."""
    limits = claude_limits()
    found = _held_for_status()
    if found is None or not limits.usage_forecast:
        return None
    held, _, cache_path, now = found
    context = _forecast_context(
        cache_path, {each.name: each.resets_at for each in held.windows}, now
    )
    return forecast_line(
        sorted(context.windows, key=lambda w: w.name != "session"),
        records=_account_ledger(cache_path),
        verdicts=context.verdicts,
        steps=context.steps,
        timers=context.timers,
        running=running,
        now=now,
        min_runs=limits.usage_forecast_min_runs,
        quantile=limits.usage_forecast_quantile,
    )


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


GUARD_OFF_LINE = (
    "usage guard off (ABK_USAGE_GUARD) — no usage is read and no start is held for usage"
)


def guard_off_line() -> str | None:
    """What a tick and the status say when this process runs with the guard off, else None."""
    return GUARD_OFF_LINE if settings.usage_guard == "off" else None


def decide_start(
    *,
    read: Callable[[], UsageReading | None] | None = None,
    decide: Callable[..., Decision] | None = None,
    unit: str | None = None,
    step: str | None = None,
    step_round: int | None = None,
    review_tier: ReviewTier | None = None,
    estimated_lines: int | None = None,
    account: claude_account.Account | None = None,
    plan_due: bool = False,
) -> Decision:
    """`_decide_start` for `account`'s windows, limits and cache; a refusal on a labelled
    account says which account is full. `step` is the step the start is for and `step_round`
    its round; a step with no round is not recorded. `plan_due` says a plan call is due, whose
    mean cost the forecast reserves. What a `starting` block names is the
    default for the unit, review tier, estimated lines, step and round, which the forecast of
    the start is made from."""
    named = _facts.get() or Ask()
    ask = Ask(
        unit=unit or _starting.get(),
        tier=review_tier or named.tier,
        lines=estimated_lines if estimated_lines is not None else named.lines,
        step=step or named.step,
        step_round=step_round if step_round is not None else named.step_round,
        plan_due=plan_due or named.plan_due,
    )
    with on_account(account):
        decision = _decide_start(read=read, decide=decide, unit=unit, step=ask.step, ask=ask)
        if decision.may_start and decision.source != "off":
            _record_step(ask)
    if account is not None and account.label is not None and not decision.may_start:
        return decision.model_copy(update={"reason": f"account {account.label}: {decision.reason}"})
    return decision


def _forecast_row(ask: Ask, cache_path: Path, now: datetime) -> ForecastRow | None:
    """What the unit asking is forecast to spend over its whole path, in each window, for the
    row written when its first step is admitted; none for a call outside a unit's graph."""
    if ask.unit is None or not ask.is_unit:
        return None
    limits = claude_limits()
    context = _forecast_context(cache_path, {"session": None, "weekly": None}, now)
    ledger = _account_ledger(cache_path)
    found = {
        each.name: forecast_unit(
            ledger,
            context.verdicts,
            tier=ask.tier,
            estimated_lines=ask.lines,
            points_per_usd=each.points_per_usd,
            flat_allowance=each.flat_allowance,
            min_runs=limits.usage_forecast_min_runs,
            quantile=limits.usage_forecast_quantile,
        )
        for each in context.windows
    }
    session, weekly = found["session"], found["weekly"]
    # The dollars and their parts do not depend on the window; a window on the prior has none.
    costed = session if session.usd is not None else weekly
    return ForecastRow(
        unit=ask.unit,
        tier=ask.tier,
        band=costed.band,
        at=now,
        session=WindowForecast(usd=session.usd, points=session.points),
        weekly=WindowForecast(usd=weekly.usd, points=weekly.points),
        parts={f"{p.role}/{p.node}/{p.round}": p.usd for p in costed.parts},
        prior=session.prior or weekly.prior,
    )


def _record_step(ask: Ask) -> None:
    """Add the step an admitted unit is about to run to the forecast record, with the unit's
    forecast when this is its first step."""
    if ask.unit is None or ask.step is None or ask.step_round is None:
        return
    limits = claude_limits()
    if not limits.usage_forecast:
        return
    cache_path = _cache_file()
    path = cache_path.parent / FORECASTS_NAME
    now = datetime.now(UTC)
    # Only a unit with no forecast row yet needs one made.
    first = all(row.unit != ask.unit for row in read_record(path).forecasts)
    record_admission(
        path,
        StepRow(unit=ask.unit, node=ask.step, round=ask.step_round, at=now),
        _forecast_row(ask, cache_path, now) if first else None,
        enabled=True,
        say=log.warning,
    )


def _decide_start(
    *,
    read: Callable[[], UsageReading | None] | None = None,
    decide: Callable[..., Decision] | None = None,
    unit: str | None = None,
    step: str | None = None,
    ask: Ask | None = None,
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
    if settings.usage_guard == "off":
        return Decision(may_start=True, reason="usage guard off (ABK_USAGE_GUARD)", source="off")
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
            base,
            _load_cache(cache_path),
            cache_path,
            now=later,
            unit=unit,
            step=step,
            ask=ask,
            next_call=next_call,
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
        decision = _forecasted(carrying(judge(reading), reading), reading, ask)
        unusable = reading is None or (not reading.is_live and reading.age > MAX_ANCHOR_AGE)
        base = _estimable(held)
        if decision.may_start or not unusable or base is None:
            return decision
        # No reading, or one too stale to use: the reading kept may still say there is room.
        return on_estimate(base, decision, next_call=next_call_at(calls_file, now=now))

    now = datetime.now(UTC)
    cache_path = _cache_file()
    calls_file = _calls_file(cache_path)
    held = _kept_reading(_load_cache(cache_path))
    if (block := _fresh_claude_block(held)) is not None:
        # A reading of Claude Code's own: it settles the decision without a call, even inside the
        # minimum interval, and is written nowhere.
        record_call(
            calls_file,
            UsageCall(
                account=claude_account.account_key(account_in_force()),
                at=now,
                caller=_caller.get(),
                outcome=CLAUDE_JSON,
                age_seconds=int(block.age.total_seconds()),
            ),
        )
        judged = _forecasted(carrying(judge(block, trust_age=True), block), block, ask)
        return _labelled(judged, block)
    if held is not None and not _past_reset(held, now):
        decision = carrying(judge(held, trust_age=True), held)
        if not decision.may_start or _headroom_holds(held, calls_file, now):
            # Answered from the reading held, as a cache hit is, so the record's share is true.
            record_call(
                calls_file,
                UsageCall(
                    account=claude_account.account_key(account_in_force()),
                    at=now,
                    caller=_caller.get(),
                    outcome=CACHE,
                    age_seconds=int((now - held.observed_at).total_seconds()),
                ),
            )
            return _forecasted(decision, held, ask)
        if now - held.observed_at < current_cache_interval(calls_file).kept:
            return fresh()
    allowed = next_call_at(calls_file, now=now)
    if allowed is not None:
        soon = _too_soon(allowed, now)
        if held is not None:
            soon = soon.model_copy(update=_reading_facts(held))
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
    # The threshold in words, with where it is moving to while it moves.
    threshold_note: str = ""
    # When a held result stops standing without a later reading: the window's end,
    # or one cache time on for a command.
    until: datetime | None = None
    # When the reading behind the result was taken; None when none was.
    taken_at: datetime | None = None


def provider_decision(
    reading: ProviderReading,
    *,
    limits: ProviderLimitsConfig,
    now: datetime,
    standing: bool = False,
) -> GateResult:
    """Whether a provider's month leaves room, by the threshold the Claude Code windows use.

    The reading is judged as read: no allowance, estimate or staleness rule applies, and
    it says nothing at or after the end of the window it assumed. A hold that stands lifts
    only when the usage plus the resume buffer is at or below the threshold; one that does
    not begins at `used >= threshold`.
    """
    figures = {
        "used_amount": reading.used_amount,
        "used_pct": reading.used_pct,
        "window_end": reading.window_end,
    }
    if now >= reading.window_end:
        return GateResult(state="unknown", reason="the reading's window has ended", **figures)
    band = _band(limits)
    window = Window(
        name=PROVIDER_WINDOW,
        used_pct=reading.used_pct,
        resets_at=reading.window_end,
        length=reading.window_end - reading.window_start,
    )
    # A provider has the one window, so its band fills both slots of `Limits`.
    ramp = Limits(session=band, weekly=band)
    threshold = threshold_at(window, now=now, limits=ramp)
    if standing:
        # The room rule is `relief_at`'s: usage plus the resume buffer, offered by the ramp.
        relief = relief_at(window, now=now, limits=ramp)
        held = relief is None or relief > now
    else:
        held = reading.used_pct >= threshold
    note = _threshold_note(window, threshold, ramp)
    return GateResult(
        state="held" if held else "usable",
        reason=f"{reading.used_pct}% used, {note}",
        threshold=threshold,
        threshold_note=note,
        until=reading.window_end if held else None,
        **figures,
    )


def _gate_cache_entry(path: Path, split: str) -> dict | None:
    entry = _load_json_object(path).get(split)
    return entry if isinstance(entry, dict) else None


def _gate_source(gate: GateConfig) -> list:
    """What an answer was taken for: the provider and budget, or the command, so a cached
    answer is never replayed under a gate that asks something else."""
    if gate.provider is not None:
        return ["provider", gate.provider.name, gate.provider.budget_usd]
    return ["command", *(gate.command or [])]


def _gate_entry_answer(
    entry: dict | None, gate: GateConfig
) -> tuple[ProviderReading | ProviderUnknown | GateCommandResult, datetime, bool] | None:
    """The answer a cache entry holds, when it was taken, and whether it is an unknown one; None
    when the entry is unreadable or was taken for another gate. Its age is not looked at."""
    if entry is None or entry.get("source") != _gate_source(gate):
        return None
    try:
        taken = datetime.fromisoformat(entry["taken_at"])
        kind = entry["kind"]
        answer: ProviderReading | ProviderUnknown | GateCommandResult
        if kind == "reading":
            answer = ProviderReading.model_validate(entry["answer"])
        elif kind == "unknown":
            answer = ProviderUnknown.model_validate(entry["answer"])
        else:
            answer = GateCommandResult.model_validate(entry["answer"])
    except (KeyError, TypeError, ValueError):
        return None
    unknown = kind == "unknown" or getattr(answer, "state", "") == "unknown"
    return answer, taken, unknown


def _gate_cached_result(
    entry: dict | None, gate: GateConfig, now: datetime
) -> ProviderReading | ProviderUnknown | GateCommandResult | None:
    """What the cache entry still answers, or None when it is spent, unreadable or was taken
    for another gate."""
    held = _gate_entry_answer(entry, gate)
    if held is None:
        return None
    answer, taken, unknown = held
    life = timedelta(
        minutes=gate.usage_stale_retry_minutes if unknown else gate.usage_cache_minutes
    )
    if not taken <= now < taken + life:
        return None
    if isinstance(answer, ProviderReading) and now >= answer.window_end:
        return None
    return answer


def _gate_answer_result(
    answer: ProviderReading | ProviderUnknown | GateCommandResult,
    gate: GateConfig,
    *,
    taken: datetime,
    now: datetime,
    standing: bool,
) -> GateResult:
    if isinstance(answer, ProviderUnknown):
        return GateResult(state="unknown", reason=answer.reason, taken_at=taken)
    if isinstance(answer, GateCommandResult):
        until = taken + timedelta(minutes=gate.usage_cache_minutes)
        return GateResult(
            state=answer.state,
            reason=answer.reason,
            until=until if answer.state == "held" else None,
            taken_at=taken,
        )
    provider = gate.provider
    assert provider is not None
    result = provider_decision(answer, limits=provider.limits, now=now, standing=standing)
    update: dict[str, object] = {"taken_at": taken}
    if result.state == "held":
        update["reason"] = (
            f"{provider.name} usage {answer.used_amount:.2f} of {provider.budget_usd:g} USD, "
            + result.reason
        )
    return result.model_copy(update=update)


def gate_result(
    split: str,
    gate: GateConfig,
    *,
    now: datetime,
    state_dir: Path,
    root: Path,
    standing: bool = False,
    refresh: bool = False,
    persist: bool = True,
    fetch: bool = True,
    read: Callable[[], object] | None = None,
    run: Run = subprocess.run,
) -> GateResult:
    """One split's gate evaluated from its configuration, through the per-split cache in
    `<state_dir>/gate-usage.json` unless `refresh`; with `fetch` off nothing is asked of the
    provider or run, and the last entry recorded for this gate answers whatever its age (an
    unknown result saying so when there is none).

    A good reading answers for `usage_cache_minutes` and never past its window's end, an unknown
    result for `usage_stale_retry_minutes`; the file is written whole under a lock, and not at all
    with `persist=False` (a dry run).
    """
    path = state_dir / GATE_USAGE_NAME
    lock = path.with_name(path.name + ".lock")
    with file_lock(lock):
        entry = _gate_cache_entry(path, split)
        cached = None if refresh else _gate_cached_result(entry, gate, now)
    if cached is not None and entry is not None:
        taken = datetime.fromisoformat(entry["taken_at"])
        return _gate_answer_result(cached, gate, taken=taken, now=now, standing=standing)

    if not fetch:
        last = _gate_entry_answer(entry, gate)
        if last is None:
            return GateResult(state="unknown", reason=NOT_READ_REASON)
        return _gate_answer_result(last[0], gate, taken=last[1], now=now, standing=standing)

    # The lock is not held across the fetch: a provider that hangs must not keep the
    # readers of the cache waiting.
    if gate.provider is not None:
        answer = read_provider_usage(
            gate.provider.name, budget_usd=gate.provider.budget_usd, now=now, read=read
        )
    else:
        assert gate.command is not None
        answer = run_gate_command(
            gate.command, root=root, timeout_seconds=gate.timeout_seconds, run=run
        )
    kind = (
        "reading"
        if isinstance(answer, ProviderReading)
        else "unknown"
        if isinstance(answer, ProviderUnknown)
        else "command"
    )
    if not persist:
        return _gate_answer_result(answer, gate, taken=now, now=now, standing=standing)
    with file_lock(lock):
        body = _load_json_object(path)
        body[split] = {
            "taken_at": now.isoformat(),
            "source": _gate_source(gate),
            "kind": kind,
            "answer": answer.model_dump(mode="json"),
        }
        atomic_write_text(path, json.dumps(body, indent=2))
    return _gate_answer_result(answer, gate, taken=now, now=now, standing=standing)


def _load_json_object(path: Path) -> dict:
    try:
        body = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    return body if isinstance(body, dict) else {}
