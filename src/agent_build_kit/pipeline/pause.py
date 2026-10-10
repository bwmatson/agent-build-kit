"""Pausing when the usage window runs low, and coming back.

`usage_guard` decides whether a unit may start. This is what happens when it
says no (docs/architecture.md).

The way back is the tick itself. The timer runs it every few minutes whether or
not anything is paused, so a pause needs no resume of its own: each tick asks
the guard again, and the first one it allows clears the marker. That also makes
a pause answer to what changed since it was written — a threshold raised by
hand, or the ramp towards the reset offering room — instead of sleeping to a
deadline worked out before either. A separate transient timer used to be
scheduled per pause, and ignored both.

A refusal from the model itself (a rate limit) is different: its reset comes
from the API, and asking the usage endpoint instead can say there is room when
there is not. That kind of pause is honoured until its deadline.

It is also deliberately visible. A marker file plus a run-log line means the
state reads as "paused until 20:51 because the weekly window is at 92%",
rather than "idle since lunchtime for reasons unknown".
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

from agent_build_kit.model import Frozen

# Just after the reset, never exactly on it: a resume racing the window
# boundary finds it still full and pauses again.
RESUME_GRACE = timedelta(minutes=2)

# When the reset time is unknown, try again on this cadence rather than
# waiting for a human.
UNKNOWN_RETRY = timedelta(minutes=30)

# The guard's own refusal, re-checked every tick; or the model's, kept to its
# deadline.
PauseKind = Literal["usage", "rate_limit"]


class Pause(Frozen):
    until: datetime
    reason: str
    kind: PauseKind = "usage"


def is_paused(marker: Path) -> Pause | None:
    """The current pause, if one is still in force.

    A pause whose deadline has passed is treated as over even if the scheduled
    resume never fired — a reboot or a disabled timer shouldn't strand the
    pipeline. An unreadable marker is treated as "not paused": unlike the unit
    store, guessing wrong here costs one usage check, not rebuilt work.
    """
    try:
        data = json.loads(marker.read_text())
        until = datetime.fromisoformat(data["until"])
    except (OSError, ValueError, KeyError, TypeError):
        return None

    if until <= datetime.now(UTC):
        return None
    kind = "rate_limit" if data.get("kind") == "rate_limit" else "usage"
    return Pause(until=until, reason=str(data.get("reason", "")), kind=kind)


def resume_deadline(until: datetime | None, *, now: datetime | None = None) -> datetime:
    """When a pause ends: the grace past `until`, added here and nowhere else.

    A reset time that is not in the future is unknown, so a pause is never
    written already over.
    """
    now = now or datetime.now(UTC)
    if until is None or until <= now:
        return now + UNKNOWN_RETRY
    return until + RESUME_GRACE


def pause_until(
    until: datetime | None, *, reason: str, marker: Path, kind: PauseKind = "usage"
) -> Pause:
    """Record a pause: until when, why, and what kind.

    A usage pause replaces the one before it, sooner or later: it is the guard's
    latest answer, and the one before was worked out from an older reading. A
    rate-limit pause is never shortened — not by another, and not by a usage
    pause, since the usage endpoint can show room the model has just refused.
    """
    deadline = resume_deadline(until)

    existing = is_paused(marker)
    if existing and existing.kind == "rate_limit" and existing.until > deadline:
        return existing

    marker.parent.mkdir(parents=True, exist_ok=True)
    # Written aside and renamed into place: a tick reads the marker while a
    # build records a pause, and a torn file would read as "not paused".
    partial = marker.with_name(f"{marker.name}.tmp")
    partial.write_text(
        json.dumps(
            {
                "until": deadline.isoformat(),
                "reason": reason,
                "kind": kind,
                "at": datetime.now(UTC).isoformat(),
            },
            indent=2,
        )
        + "\n"
    )
    os.replace(partial, marker)
    return Pause(until=deadline, reason=reason, kind=kind)


def pause_line(pause: Pause, *, verb: str = "paused", now: datetime | None = None) -> str:
    """The run-log line announcing a pause: its end in local time, and why.

    The end is never shown earlier than `now`, the moment the line is printed.
    """
    now = now or datetime.now(UTC)
    end = max(pause.until, now).astimezone()
    return f"{verb} until {end:%H:%M} — {pause.reason}"


def clear_pause(marker: Path) -> None:
    marker.unlink(missing_ok=True)
