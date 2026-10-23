"""The cost reserved for a plan call that is due and the tracks whose timers fire before a window
resets (spec: usage-pause)."""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Collection, Sequence
from datetime import datetime
from pathlib import Path

from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.usage_ledger import UsageRecord

Run = Callable[..., subprocess.CompletedProcess]


class TrackTimer(Frozen):
    """When a track's timer next elapses and last fired, where systemd said."""

    next_elapse: datetime | None
    last_trigger: datetime | None


class TimerReading(Frozen):
    """The installed track timers by track node (`track_health`, ...), or that they could not be
    read (no systemd, not installed)."""

    read: bool
    tracks: dict[str, TrackTimer]


class Reservation(Frozen):
    """What one plan call or track holds back: its mean cost in dollars and points."""

    name: str
    usd: float
    points: float


class Reserved(Frozen):
    """The reservations for one window, and whether the timers were read."""

    items: tuple[Reservation, ...]
    timers_read: bool


def read_timers(root: Path, *, run: Run = subprocess.run) -> TimerReading:
    """The next elapse and last trigger of each installed track timer of the installation at
    `root`, from `systemctl --user show`; unread when it cannot be run or answers with an error."""
    raise NotImplementedError


def reserve(
    records: Sequence[UsageRecord],
    timers: TimerReading,
    *,
    plan_due: bool,
    proposing: Collection[str],
    resets_at: datetime,
    now: datetime,
    points_per_usd: float,
) -> Reserved:
    """A plan call when `plan_due`, and each track whose timer next elapses in `[now, resets_at)`
    or has fired with no ledger row of the track since, each at the mean cost of its node in
    `records`; `track_propose` is added with a track named in `proposing`. Nothing is reserved
    for a track when the timers were not read."""
    raise NotImplementedError
