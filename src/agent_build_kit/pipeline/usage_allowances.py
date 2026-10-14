"""The allowance of each usage window, calibrated from the readings and the ledger on disk.

A pair is two consecutive good readings of a window and the units that spent between them;
the allowance is a high quantile of points gained per unit over the newest pairs, kept
between a floor and a ceiling, and applied only with enough pairs (spec: usage-pause).
The tick computes it once and keeps it beside the guard's cache file."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal

from pydantic import ValidationError

from agent_build_kit import claude_account
from agent_build_kit.config import ClaudeLimitsConfig
from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.file_lock import atomic_write_text
from agent_build_kit.pipeline.usage_calls import (
    CALLS_NAME,
    UsageCall,
    consecutive_readings,
    parse_calls,
)
from agent_build_kit.pipeline.usage_ledger import LEDGER_NAME, UsageRecord, read_ledger, spend_times

ALLOWANCES_NAME = "usage-allowances.json"

Window = Literal["session", "weekly"]
WINDOWS: tuple[Window, ...] = ("session", "weekly")
# The two windows' lengths, which the endpoint doesn't report. A longer gap between readings
# may span a reset followed by a climb.
SESSION_WINDOW = timedelta(hours=5)
WEEKLY_WINDOW = timedelta(days=7)
SPANS: dict[Window, timedelta] = {"session": SESSION_WINDOW, "weekly": WEEKLY_WINDOW}


class UsagePair(Frozen):
    """Two good readings of a window and the units that spent between them."""

    at: datetime  # the earlier reading
    before: int  # the figure at the earlier reading
    gain: int  # points gained between the readings
    units: int  # distinct units with an agent record in [earlier, later)


class Calibrated(Frozen):
    """What the history gave for one window, kept with the inputs behind it."""

    quantile_pct_per_unit: float | None  # None: too few pairs to calibrate
    quantile: float
    pairs_used: int
    pairs_available: int
    computed_at: datetime


def pairs(
    calls: list[UsageCall], ledger: list[UsageRecord], window: Window, *, min_gap: timedelta
) -> list[UsagePair]:
    """The usable pairs of `window`, oldest first. Each reading is paired with the next one at
    least `min_gap` later, as `most_added` does; a fall, a gap longer than the window's
    span and a gap in which no unit spent make no pair."""
    spent = spend_times(ledger)
    made = []
    for before, low, after, high in consecutive_readings(calls, window, min_gap=min_gap):
        units = len({unit for at, unit in spent if before <= at < after})
        if high >= low and after - before <= SPANS[window] and units:
            made.append(UsagePair(at=before, before=low, gain=high - low, units=units))
    return made


def calibrate_pairs(
    usable: list[UsagePair], *, limits: ClaudeLimitsConfig, now: datetime
) -> Calibrated:
    """The calibration of one window from its usable pairs, oldest first."""
    newest = usable[-limits.usage_allowance_window :]
    figure = None
    if len(usable) >= limits.usage_allowance_min_pairs:
        samples = sorted(p.gain / p.units for p in newest)
        rank = math.ceil(round(limits.usage_allowance_quantile * len(samples), 9))
        figure = samples[max(rank, 1) - 1]
    return Calibrated(
        quantile_pct_per_unit=figure,
        quantile=limits.usage_allowance_quantile,
        pairs_used=len(newest) if figure is not None else 0,
        pairs_available=len(usable),
        computed_at=now,
    )


def since_last_change(calls: list[UsageCall], account: str | None) -> list[UsageCall]:
    """The lines after the last one of an account other than `account`, so readings of one
    account are never paired with another's."""
    for index in range(len(calls) - 1, -1, -1):
        if calls[index].account != account:
            return calls[index + 1 :]
    return calls


def calibrated_allowances(
    calls: list[UsageCall],
    ledger: list[UsageRecord],
    *,
    limits: ClaudeLimitsConfig,
    now: datetime,
) -> dict[str, Calibrated]:
    """Each window's calibration from the record; none with calibration off."""
    if not limits.calibrate_usage_allowances:
        return {}
    min_gap = timedelta(minutes=limits.usage_cache_minutes)
    calls = since_last_change(calls, claude_account.account_key())
    found: dict[str, Calibrated] = {}
    for window in WINDOWS:
        usable = pairs(calls, ledger, window, min_gap=min_gap)
        found[window] = calibrate_pairs(usable, limits=limits, now=now)
    return found


def allowance_for(window: Window, found: Calibrated | None, limits: ClaudeLimitsConfig) -> int:
    """The allowance in force: the calibrated figure rounded up and kept between the floor and
    the ceiling, else the configured one, and always the configured one with calibration off."""
    configured = limits.configured_allowance(window)
    if not limits.calibrate_usage_allowances or found is None:
        return configured
    if found.quantile_pct_per_unit is None:
        return configured
    floor = getattr(limits, window).usage_allowance_floor_pct
    return min(max(math.ceil(found.quantile_pct_per_unit), floor), limits.allowance_ceiling(window))


def allowances_line(found: Mapping[str, Calibrated], limits: ClaudeLimitsConfig) -> str:
    """The allowances in force and the pairs behind them, for `abk status`."""
    head = "usage allowances:"
    if not limits.calibrate_usage_allowances:
        return f"{head} fixed (calibration off)"
    needed = limits.usage_allowance_min_pairs
    parts, calibrated = [], []
    for window in WINDOWS:
        kept = found.get(window)
        applied = allowance_for(window, kept, limits)
        if kept is None or kept.quantile_pct_per_unit is None:
            held = 0 if kept is None else kept.pairs_available
            parts.append(f"{window} {applied}/unit default ({held} pairs of {needed} needed)")
            calibrated.append(False)
            continue
        raw = math.ceil(kept.quantile_pct_per_unit)
        mark = ", capped" if applied < raw else ", floor" if applied > raw else ""
        parts.append(f"{window} {applied}/unit ({kept.pairs_used} pairs{mark})")
        calibrated.append(True)
    if not any(calibrated):
        held = {found[w].pairs_available if w in found else 0 for w in WINDOWS}
        if len(held) == 1:
            return f"{head} defaults ({held.pop()} pairs of {needed} needed)"
    return f"{head} {', '.join(parts)}" + (", calibrated" if all(calibrated) else "")


def read_allowances(path: Path) -> dict[str, Calibrated]:
    """The kept result; empty when the file is missing, unreadable or of another shape."""
    try:
        body = json.loads(path.read_text())
        if not isinstance(body, dict):
            return {}
        return {name: Calibrated.model_validate(each) for name, each in body.items()}
    except (OSError, ValueError, ValidationError):
        return {}


def write_allowances(path: Path, found: Mapping[str, Calibrated]) -> None:
    """Keep `found` whole: a reader never sees half of it."""
    body = {name: each.model_dump(mode="json") for name, each in found.items()}
    atomic_write_text(path, json.dumps(body, indent=2))


def refresh_allowances(state_dir: Path, *, limits: ClaudeLimitsConfig, now: datetime) -> None:
    """Compute from the files in `state_dir` and keep the result, leaving it as it was when
    a file cannot be read or the result cannot be kept."""
    try:
        try:
            calls = parse_calls((state_dir / CALLS_NAME).read_text())
        except FileNotFoundError:
            calls = []
        ledger = read_ledger(state_dir / LEDGER_NAME)
        write_allowances(
            state_dir / ALLOWANCES_NAME,
            calibrated_allowances(calls, ledger, limits=limits, now=now),
        )
    except OSError:
        return
