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
2. **`~/.claude.json`'s `cachedUsageUtilization`**, the same numbers cached
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
import os
import re
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

from agent_build_kit.config import (
    CLAUDE_CODE,
    RuntimeConfig,
    UsageWindowConfig,
    active,
    active_root,
)
from agent_build_kit.model import Frozen
from agent_build_kit.runtimes.base import AgentInterrupted, AgentRateLimited

USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
OAUTH_BETA_HEADER = "oauth-2025-04-20"
CREDENTIALS_PATH = Path.home() / ".claude" / ".credentials.json"
DEFAULT_ANCHOR_PATH = Path.home() / ".claude.json"

# The endpoint belongs to somebody else and a start-check runs often, so
# repeated checks inside this window reuse the cached response.
LIVE_TTL = timedelta(minutes=3)

# How old a *cached-file* reading may be before it says nothing useful. The
# five-hour window is the shorter of the two, so an hour is already a
# meaningful fraction of it. Live readings are exempt: they were just taken.
MAX_ANCHOR_AGE = timedelta(hours=1)

# Resuming exactly at the reset would race the window boundary and pause again.
RESUME_GRACE = timedelta(minutes=2)

# How long to wait before looking again when the reading is unusable. Short
# enough to pick up a recovered endpoint, long enough not to spin.
UNKNOWN_RETRY = timedelta(minutes=30)

# The two windows' lengths, which the endpoint doesn't report. A window's start
# is its reset minus its length, and that is all the ramp needs.
SESSION_WINDOW = timedelta(hours=5)
WEEKLY_WINDOW = timedelta(days=7)

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


def read_oauth_token(path: Path | None = None) -> str | None:
    """Find Claude Code's stored OAuth token.

    Read-only, and the value is never logged or written anywhere by this
    module — it goes straight into the Authorization header.
    """
    from_env = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN")
    if from_env:
        return from_env

    try:
        raw = json.loads((path or CREDENTIALS_PATH).read_text())
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
    if reading.resets_at is None:
        return datetime.now(UTC) + UNKNOWN_RETRY
    return reading.resets_at + RESUME_GRACE


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
        claude = active().runtimes.get(CLAUDE_CODE, RuntimeConfig()).limits
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
    path = path or CREDENTIALS_PATH
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


def read_live_usage(
    *,
    token: str | None = None,
    fetch: Fetch = _http_get_json,
    cache_path: Path | None = None,
    ttl: timedelta = LIVE_TTL,
    expired: Callable[[], bool] | None = None,
    refresh: Callable[[], None] | None = None,
) -> UsageReading | None:
    """Ask the endpoint where the windows stand, or None if it can't say.

    The response is cached to `cache_path` so repeated start-checks inside
    `ttl` don't hammer somebody else's service. The token is never written
    there.
    """
    if cache_path is None:
        root = active_root()
        state = (
            root / active().planning.state_dir
            if root
            else Path.home() / ".cache" / "agent-build-kit"
        )
        cache_path = state / "usage-cache.json"
    now = datetime.now(UTC)

    if cache_path.exists() and ttl > timedelta(0):
        try:
            cached = json.loads(cache_path.read_text())
            fetched_at = datetime.fromisoformat(cached["fetched_at"])
            if now - fetched_at < ttl:
                return _reading_from_payload(cached, observed_at=fetched_at, source="live")
        except (OSError, ValueError, KeyError, TypeError):
            pass  # A bad cache is just a cache miss.

    given = token
    token = token or read_oauth_token()
    if not token:
        return None

    def ask(bearer: str) -> object:
        return fetch(
            USAGE_URL,
            {"Authorization": f"Bearer {bearer}", "anthropic-beta": OAUTH_BETA_HEADER},
        )

    try:
        payload = ask(token)
    except Exception:
        # An expired token is the one failure with a known fix; see
        # `refresh_login`. Only for the saved token, never one passed in.
        if given is not None or not (expired or token_expired)():
            # Any other failure — offline, 429, a contract that changed — is
            # "unknown", which pauses. Never an excuse to assume headroom.
            return None
        (refresh or refresh_login)()
        fresh = read_oauth_token()
        if not fresh or fresh == token:
            return None
        try:
            payload = ask(fresh)
        except Exception:
            return None

    reading = _reading_from_payload(payload, observed_at=now, source="live")
    if reading is None:
        return None

    if isinstance(payload, dict):
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps({**payload, "fetched_at": now.isoformat()}, indent=2))
        except (OSError, TypeError):
            pass  # Caching is an optimization, not a requirement.

    return reading


def read_cached_usage(path: Path | None = None) -> UsageReading | None:
    """Read Claude Code's own cache in ~/.claude.json, the fallback source."""
    path = path or DEFAULT_ANCHOR_PATH

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


def current_usage() -> UsageReading | None:
    """The best reading available: live if possible, else the local cache."""
    return read_live_usage() or read_cached_usage()


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
# is left `running` for the next tick's `reclaim_stale`. A refusal means the
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


def may_start_unit(reading: UsageReading | None) -> Decision:
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
    """
    now = datetime.now(UTC)

    if reading is None:
        return Decision(
            may_start=False,
            reason="usage is unknown: neither the usage endpoint nor ~/.claude.json could be read",
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

    # A live reading was just taken, so only the local cache can be stale.
    if not reading.is_live and reading.age > MAX_ANCHOR_AGE:
        return Decision(
            may_start=False,
            reason=(
                f"usage reading is stale ({int(reading.age.total_seconds() // 60)}m old, "
                f"from {reading.source}); headless runs don't refresh it"
            ),
            resume_at=_resume_after(reading),
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
    return f"{moment:%m-%d %H:%M UTC}"


def _resume_to(window: Window, *, now: datetime, limits: Limits) -> datetime:
    """When to look again after a window's threshold refused a unit.

    The ramp may clear the current usage before the reset does; if it never
    will, the reset is the answer. Either way the wait is capped, so a weekly
    window that resets days out doesn't put the pipeline to sleep for days.
    """
    relief = relief_at(window, now=now, limits=limits)
    if relief is None:
        relief = window.resets_at + RESUME_GRACE if window.resets_at else now + UNKNOWN_RETRY
    return min(relief, now + MAX_SCHEDULED_PAUSE)
