"""The cost reserved for a plan call that is due and the tracks whose timers fire before a window
resets (spec: usage-pause)."""

from __future__ import annotations

import statistics
import subprocess
from collections.abc import Callable, Collection, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.usage_forecast_running import mean_cost, record_time
from agent_build_kit.pipeline.usage_ledger import UsageRecord
from agent_build_kit.timers import slug

Run = Callable[..., subprocess.CompletedProcess]


class TrackTimer(Frozen):
    """When a track's timer next elapses and last fired, where systemd said."""

    next_elapse: datetime | None
    last_trigger: datetime | None


class TimerReading(Frozen):
    """The installed track timers by track node (`track_health`, ...), the track nodes whose
    timer is not installed, and whether any timer was read (not when there is no systemd or none
    is installed)."""

    read: bool
    tracks: dict[str, TrackTimer]
    missing: tuple[str, ...] = ()


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
_PROPERTIES = "--property=LoadState,NextElapseUSecRealtime,LastTriggerUSec"

# How many mean durations of its node after firing a track is still taken to be running.
IN_FLIGHT_DURATIONS = 3


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
    missing: list[str] = []
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
        if values.get("LoadState") != "loaded":
            missing.append(node)
            continue
        tracks[node] = TrackTimer(
            next_elapse=_moment(values.get("NextElapseUSecRealtime", "")),
            last_trigger=_moment(values.get("LastTriggerUSec", "")),
        )
    return TimerReading(read=bool(tracks), tracks=tracks, missing=tuple(missing))


def _due(
    node: str, timer: TrackTimer, records: Sequence[UsageRecord], now: datetime, resets_at: datetime
) -> bool:
    """Whether the timer fires before the reset, or fired within a few mean durations of its node
    ago and has left no ledger row yet."""
    if timer.next_elapse is not None and now <= timer.next_elapse < resets_at:
        return True
    fired = timer.last_trigger
    durations = [r.duration_ms for r in records if r.node == node and r.duration_ms]
    if fired is None or not durations:
        return False
    if now - fired > timedelta(milliseconds=IN_FLIGHT_DURATIONS * statistics.fmean(durations)):
        return False
    return not any(
        r.node == node and (at := record_time(r)) is not None and at >= fired for r in records
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
        usd = mean_cost(records, node)
        if usd is not None:
            items.append(Reservation(name=node, usd=usd, points=usd * points_per_usd))
    return Reserved(items=tuple(items), timers_read=timers.read)
