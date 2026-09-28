"""Whether there is room in the Claude usage window to start another unit.

The account is on a subscription, so the constraint isn't dollars — it's the
plan's usage window, shared with the user's own interactive sessions. Credits
are enabled past the plan limit, which means running to 100% spends real money
instead of stopping. So unattended work stops starting new units at
`spec_usage_pause_pct` (70 by default) and schedules a resume after the window
resets.

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
import subprocess
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

from agent_build_kit.config import active, active_root
from agent_build_kit.model import Frozen

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

Fetch = Callable[[str, dict[str, str]], object]


class UsageReading(Frozen):
    """Where the usage windows stood, and how we came to know it."""

    session_pct: int
    weekly_pct: int
    # None when no five-hour window is open: nothing has been used since the
    # last one ended, so there is nothing to reset. Not "unknown".
    resets_at: datetime | None
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
    """
    subprocess.run(
        ["claude", "-p", "Reply with OK and nothing else.", "--model", "haiku"],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )


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
    "429",
)

# "Claude AI usage limit reached|1919763200" — an epoch seconds reset.
RESET_EPOCH = re.compile(r"limit reached\|(\d{10,})")


class Interrupted(RuntimeError):
    """The claude process was killed by a signal, not refused and not broken.

    Says nothing about the work, so it must not fail the unit: stealth-
    browser-mcp/2's rework was SIGKILLed fourteen seconds in, recorded as
    failed, and had its tasks unticked. The unit is left `running` for the
    next tick's `reclaim_stale`, which recovers it as it does any run whose
    process died.
    """


class RateLimited(RuntimeError):
    """Anthropic refused the call: a usage window is exhausted.

    Distinct from an ordinary failure because the response is different. The
    unit is fine and the account is out of room, so the pipeline pauses rather
    than marking real work failed and dropping it from the plan.
    """

    def __init__(self, message: str, *, resets_at: datetime | None = None) -> None:
        super().__init__(message)
        self.resets_at = resets_at


def rate_limit_reset(text: str) -> datetime | None | Literal[False]:
    """Whether `text` is a refusal, and when it lifts.

    Three answers, deliberately: a `datetime` when the message says when,
    `None` when it is a refusal that does not say (the live reading supplies
    the time instead), and `False` when it is not a refusal at all. A plain
    `None` for both cases would make "no timestamp" read as "not rate
    limited", which is the one mistake that matters here.
    """
    lowered = text.lower()
    if not any(marker in lowered for marker in RATE_LIMIT_MARKERS):
        return False

    match = RESET_EPOCH.search(lowered)
    return datetime.fromtimestamp(int(match.group(1)), UTC) if match else None


def check_refusal(result: subprocess.CompletedProcess) -> None:
    """Turn a failed `claude` call into the right kind of exception.

    A non-zero exit used to be ignored — the empty stdout flowed on, the
    commit step found nothing staged, and the unit was recorded as the model
    having produced nothing. Two different things were hidden behind that: a
    run that broke, whose half-finished edits are on disk and must not be
    committed as a finished unit, and an account that is simply out of room.
    """
    if not result.returncode:
        return

    if result.returncode < 0:
        raise Interrupted(f"claude was killed by signal {-result.returncode}")

    text = f"{result.stdout}\n{result.stderr}".strip()
    reset = rate_limit_reset(text)
    if reset is not False:
        raise RateLimited(text or "claude reported a usage limit", resets_at=reset)

    raise RuntimeError(f"claude exited {result.returncode}: {text}")


def may_start_unit(reading: UsageReading | None) -> Decision:
    """Decide whether a new unit may start now.

    Units already running are not affected: this gates starting work, so
    nothing is ever left half-committed or unpushed by a pause. The headroom
    above the threshold is what pays for them finishing.

    **The threshold is the operative limit.** The credits checks below are
    backstops for the case where something has already gone wrong; they can
    only ever stop work earlier, never permit more of it. Available credits
    are the user's reserve, not headroom for the pipeline, so a healthy credit
    balance does not raise the ceiling past `spec_usage_pause_pct`.
    """
    threshold = active().limits.usage_pause_pct

    if reading is None:
        return Decision(
            may_start=False,
            reason="usage is unknown: neither the usage endpoint nor ~/.claude.json could be read",
            resume_at=datetime.now(UTC) + UNKNOWN_RETRY,
        )

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

    for window, used in (("weekly", reading.weekly_pct), ("session", reading.session_pct)):
        if used >= threshold:
            return Decision(
                may_start=False,
                reason=f"{window} usage at {used}% (threshold {threshold}%, {reading.source})",
                resume_at=_resume_after(reading),
            )

    return Decision(
        may_start=True,
        reason=(
            f"session {reading.session_pct}%, weekly {reading.weekly_pct}% "
            f"(threshold {threshold}%, {reading.source})"
        ),
    )
