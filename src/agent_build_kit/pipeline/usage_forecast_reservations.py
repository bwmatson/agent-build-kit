"""The cost reserved for a plan call that is due and the tracks whose timers fire before a window
resets (spec: usage-pause)."""

from __future__ import annotations

import statistics
import subprocess
from collections.abc import Callable, Collection, Sequence
from datetime import UTC, datetime
from pathlib import Path

from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.usage_ledger import UsageRecord
from agent_build_kit.timers import slug

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


_TRACKS = ("track_health", "track_improve", "track_recommend")
_PROPERTIES = "--property=NextElapseUSecRealtime,LastTriggerUSec"


def _moment(text: str) -> datetime | None:
    """A time as `systemctl show` prints it (`Thu 2026-01-01 13:00:00 UTC`); none for `n/a`."""
    parts = text.split()
    if len(parts) < 3:
        return None
    try:
        naive = datetime.strptime(f"{parts[1]} {parts[2]}", "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None
    return naive.replace(tzinfo=UTC) if parts[-1] == "UTC" else naive.astimezone()


def read_timers(root: Path, *, run: Run = subprocess.run) -> TimerReading:
    """The next elapse and last trigger of each installed track timer of the installation at
    `root`, from `systemctl --user show`; unread when it cannot be run or answers with an error."""
    tracks: dict[str, TrackTimer] = {}
    for node in _TRACKS:
        name = f"abk-{slug(root)}-{node.replace('_', '-')}.timer"
        try:
            shown = run(
                ["systemctl", "--user", "show", name, _PROPERTIES],
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError:
            return TimerReading(read=False, tracks={})
        if shown.returncode != 0:
            return TimerReading(read=False, tracks={})
        values = dict(line.split("=", 1) for line in shown.stdout.splitlines() if "=" in line)
        tracks[node] = TrackTimer(
            next_elapse=_moment(values.get("NextElapseUSecRealtime", "")),
            last_trigger=_moment(values.get("LastTriggerUSec", "")),
        )
    return TimerReading(read=True, tracks=tracks)


def _mean_usd(records: Sequence[UsageRecord], node: str) -> float | None:
    costs = [r.cost.incremental_usd for r in records if r.node == node and r.cost]
    costs = [c for c in costs if c is not None]
    return statistics.fmean(costs) if costs else None


def _due(
    node: str, timer: TrackTimer, records: Sequence[UsageRecord], now: datetime, resets_at: datetime
) -> bool:
    """Whether the timer fires before the reset, or has fired and left no ledger row yet."""
    if timer.next_elapse is not None and now <= timer.next_elapse < resets_at:
        return True
    fired = timer.last_trigger
    return fired is not None and not any(
        r.node == node and datetime.fromisoformat(r.at) >= fired for r in records
    )


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
    wanted = ["plan"] if plan_due else []
    if timers.read:
        for node, timer in timers.tracks.items():
            if _due(node, timer, records, now, resets_at):
                wanted += [node, *(["track_propose"] if node in proposing else [])]
    items = []
    for node in wanted:
        usd = _mean_usd(records, node)
        if usd is not None:
            items.append(Reservation(name=node, usd=usd, points=usd * points_per_usd))
    return Reserved(items=tuple(items), timers_read=timers.read)
