"""The allowance of each usage window, calibrated from the readings and the ledger on disk.

A pair is two consecutive good readings of a window and the units that spent between them;
the allowance is a high quantile of points gained per unit over the newest pairs, kept
between a floor and a ceiling, and applied only with enough pairs (spec: usage-pause).
The tick computes it once and keeps it beside the guard's cache file."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal

from pydantic import ValidationError

from agent_build_kit import claude_account
from agent_build_kit.config import ClaudeLimitsConfig
from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.file_lock import atomic_write_text
from agent_build_kit.pipeline.usage_calls import (
    UsageCall,
    calls_path,
    consecutive_readings,
    parse_calls,
)
from agent_build_kit.pipeline.usage_ledger import (
    LEDGER_NAME,
    UsageRecord,
    read_ledger,
    spend_costs,
    spend_times,
)

ALLOWANCES_NAME = "usage-allowances.json"


def allowances_path(state_dir: Path, account: claude_account.Account) -> Path:
    """The kept allowances of `account` in `state_dir`: a labelled account keeps its own file."""
    return claude_account.file_for(state_dir / ALLOWANCES_NAME, account)


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


class CostPair(Frozen):
    """Two good readings of a window and what the account recorded spending between them."""

    at: datetime  # the earlier reading
    before: int  # the figure at the earlier reading
    gain: int  # points gained between the readings
    cost_usd: float  # recorded incremental cost of the rows in [earlier, later)
    hours: float  # the length of the gap
    units: int  # distinct units with a row in the gap, none for a gap of unit-less rows


class Calibrated(Frozen):
    """What the history gave for one window, kept with the inputs behind it."""

    quantile_pct_per_unit: float | None  # None: too few pairs to calibrate
    quantile: float
    pairs_used: int
    pairs_available: int
    computed_at: datetime
    basis: Literal["cost", "units"] = "units"  # the basis in force
    reason: str | None = None  # why it is not `cost`, or that it came from the previous file
    points_per_usd: float | None = None  # the kept cost fit, safety scale included
    intercept_per_hour: float | None = None
    safety_scale: float | None = None
    cost_pairs_held: int = 0
    cost_pairs_judged: int = 0  # gaps judged walk-forward
    false_allows_cost: int = 0
    false_allows_flat: int = 0


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


def cost_pairs(
    calls: list[UsageCall], ledger: list[UsageRecord], window: Window, *, min_gap: timedelta
) -> list[CostPair]:
    """The usable cost pairs of `window`, oldest first: as `pairs`, but a gap counts by the
    cost of its rows, with a unit or without one. A gap with no recorded cost, or with a unit
    none of whose rows has a cost, makes no pair."""
    spent = spend_costs(ledger)
    made = []
    for before, low, after, high in consecutive_readings(calls, window, min_gap=min_gap):
        if high < low or after - before > SPANS[window]:
            continue
        in_gap = [row for row in spent if before <= row.at < after]
        total = sum(row.cost_usd for row in in_gap)
        by_unit: dict[str, float] = {}
        for row in in_gap:
            if row.unit:
                by_unit[row.unit] = by_unit.get(row.unit, 0.0) + row.cost_usd
        if total > 0 and all(cost > 0 for cost in by_unit.values()):
            hours = (after - before).total_seconds() / 3600
            made.append(
                CostPair(
                    at=before,
                    before=low,
                    gain=high - low,
                    cost_usd=total,
                    hours=hours,
                    units=len(by_unit),
                )
            )
    return made


class CostFit(Frozen):
    """The kept cost fit of one window: points per dollar and per hour, scale included."""

    points_per_usd: float
    intercept_per_hour: float
    safety_scale: float


def _round_up(value: float, step: float = 0.01) -> float:
    return math.ceil(round(value / step, 6)) * step if value > 0 else 0.0


def _fit_coefficients(usable: list[CostPair], intercept: bool) -> tuple[float, float] | None:
    """The non-negative least-squares coefficients of gain on cost (and hours), else None."""
    sxx = sum(p.cost_usd**2 for p in usable)
    sxy = sum(p.cost_usd * p.gain for p in usable)
    if intercept:
        shh = sum(p.hours**2 for p in usable)
        sxh = sum(p.cost_usd * p.hours for p in usable)
        shy = sum(p.hours * p.gain for p in usable)
        det = sxx * shh - sxh**2
        if det > 1e-9 * sxx * shh:
            per_usd = (sxy * shh - shy * sxh) / det
            per_hour = (sxx * shy - sxh * sxy) / det
            if per_usd <= 1e-9:
                return None
            if per_hour >= 0:
                return per_usd, per_hour
    per_usd = sxy / sxx
    return (per_usd, 0.0) if per_usd > 1e-9 else None


def fit_cost(
    usable: list[CostPair], *, limits: ClaudeLimitsConfig, window: Window
) -> CostFit | None:
    """The cost fit of `window` over the newest pairs of `usable`: the non-negative line of
    gain on cost (and hours where the window's intercept is on), times the residual-quantile
    safety scale kept between 1 and 2, rounded up to 0.01. None for no fit."""
    newest = usable[-limits.usage_allowance_window :]
    if len(newest) < limits.usage_cost_min_pairs:
        return None
    found = _fit_coefficients(newest, getattr(limits, window).usage_estimate_intercept)
    if found is None:
        return None
    per_usd, per_hour = found
    ratios = sorted(
        round(p.gain / predicted, 9)
        for p in newest
        if (predicted := per_usd * p.cost_usd + per_hour * p.hours) > 0
    )
    scale = 1.0
    if ratios:
        rank = math.ceil(round(limits.usage_cost_quantile * len(ratios), 9))
        scale = min(max(ratios[max(rank, 1) - 1], 1.0), 2.0)
    return CostFit(
        points_per_usd=_round_up(per_usd * scale),
        intercept_per_hour=_round_up(per_hour * scale),
        safety_scale=scale,
    )


def gap_estimates(
    index: int,
    usable: list[CostPair],
    flat_pairs: list[UsagePair],
    *,
    limits: ClaudeLimitsConfig,
    window: Window,
    now: datetime,
    fixed: int | None = None,
) -> tuple[float, float | None]:
    """The points spent in cost pair `usable[index]` as the flat figure and as the cost fit
    estimate it, each made from the pairs before it only. The flat figure counts the gap's
    units at the calibrated allowance (`fixed` when given), none for a gap with no unit; the
    cost one is None where the pairs before make no fit."""
    pair = usable[index]
    allowance = fixed
    if allowance is None:
        flat = calibrate_pairs([p for p in flat_pairs if p.at < pair.at], limits=limits, now=now)
        allowance = allowance_for(window, flat, limits)
    fit = fit_cost(usable[:index], limits=limits, window=window)
    if fit is None:
        return pair.units * allowance, None
    spent = fit.points_per_usd * pair.cost_usd + fit.intercept_per_hour * pair.hours
    return pair.units * allowance, spent


def _false_allows(
    newest: list[CostPair],
    offset: int,
    usable: list[CostPair],
    flat_pairs: list[UsagePair],
    *,
    limits: ClaudeLimitsConfig,
    window: Window,
    now: datetime,
) -> tuple[int, int, int]:
    """(gaps judged, false allows of the cost fit, false allows of the flat figure) walk-forward
    over `newest`, each gap estimated from the pairs before it."""
    threshold = getattr(limits, window).usage_pause_pct
    margin = limits.usage_headroom_margin_pct
    judged = cost_false = flat_false = 0
    for index in range(limits.usage_cost_min_pairs, len(newest)):
        pair = newest[index]
        flat_estimate, cost_estimate = gap_estimates(
            offset + index, usable, flat_pairs, limits=limits, window=window, now=now
        )
        estimate = flat_estimate if cost_estimate is None else cost_estimate
        reached = pair.before + pair.gain >= threshold
        judged += 1
        cost_false += reached and pair.before + estimate + margin < threshold
        flat_false += reached and pair.before + flat_estimate + margin < threshold
    return judged, cost_false, flat_false


def calibrate_cost(
    flat: Calibrated,
    usable: list[CostPair],
    flat_pairs: list[UsagePair],
    *,
    limits: ClaudeLimitsConfig,
    window: Window,
    now: datetime,
) -> Calibrated:
    """`flat` with the cost fit of `window`, and the basis in force with its reason."""
    held = {"cost_pairs_held": len(usable)}
    if len(usable) < limits.usage_cost_min_pairs:
        return flat.model_copy(update={**held, "reason": "too_few_pairs"})
    fit = fit_cost(usable, limits=limits, window=window)
    if fit is None:
        return flat.model_copy(update={**held, "reason": "no_fit"})
    newest = usable[-limits.usage_allowance_window :]
    judged, cost_false, flat_false = _false_allows(
        newest,
        len(usable) - len(newest),
        usable,
        flat_pairs,
        limits=limits,
        window=window,
        now=now,
    )
    adopted = judged >= limits.usage_cost_min_pairs and cost_false <= flat_false
    reason = (
        None
        if adopted
        else "too_few_judged"
        if judged < limits.usage_cost_min_pairs
        else "more_false_allows"
    )
    return flat.model_copy(
        update={
            **held,
            **fit.model_dump(),
            "basis": "cost" if adopted else "units",
            "reason": reason,
            "cost_pairs_judged": judged,
            "false_allows_cost": cost_false,
            "false_allows_flat": flat_false,
        }
    )


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


def of_account(
    calls: list[UsageCall], ledger: list[UsageRecord], account: claude_account.Account
) -> tuple[list[UsageCall], list[UsageRecord]]:
    """The readings of `account` and the units that ran on it. A labelled account takes only
    what carries its key; a row with no key (written by the default account, or before the
    ledger carried one) counts for the default account alone."""
    key = claude_account.account_key(account)
    default = account.label is None
    return (
        [call for call in calls if call.account == key],
        [row for row in ledger if row.account == key or (default and row.account is None)],
    )


def calibrated_allowances(
    calls: list[UsageCall],
    ledger: list[UsageRecord],
    *,
    limits: ClaudeLimitsConfig,
    now: datetime,
    account: claude_account.Account | None = None,
) -> dict[str, Calibrated]:
    """Each window's calibration from the record; none with calibration off. Without `account`
    the default account's: its readings after the last one of another account, and the units
    no labelled account ran."""
    if not limits.calibrate_usage_allowances:
        return {}
    min_gap = timedelta(minutes=limits.usage_cache_minutes)
    if account is None:
        default = claude_account.Account.default()
        calls = since_last_change(calls, claude_account.account_key(default))
        ledger = of_account([], ledger, default)[1]
    else:
        calls, ledger = of_account(calls, ledger, account)
    found: dict[str, Calibrated] = {}
    for window in WINDOWS:
        usable = pairs(calls, ledger, window, min_gap=min_gap)
        flat = calibrate_pairs(usable, limits=limits, now=now)
        if getattr(limits, window).usage_estimate_basis == "units":
            found[window] = flat.model_copy(update={"reason": "basis_units"})
            continue
        found[window] = calibrate_cost(
            flat,
            cost_pairs(calls, ledger, window, min_gap=min_gap),
            usable,
            limits=limits,
            window=window,
            now=now,
        )
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


def cost_basis_in_force(
    window: Window, found: Calibrated | None, limits: ClaudeLimitsConfig
) -> bool:
    """Whether `window` is estimated from recorded cost: calibration is on, the kept entry is
    on the cost basis with a fit, and the window's setting asks for the cost basis."""
    return (
        limits.calibrate_usage_allowances
        and found is not None
        and found.basis == "cost"
        and found.points_per_usd is not None
        and getattr(limits, window).usage_estimate_basis == "cost"
    )


def _why_flat(kept: Calibrated, limits: ClaudeLimitsConfig) -> str:
    """After a flat part, why the cost basis is not in force for the window."""
    needed = limits.usage_cost_min_pairs
    pairs_held, judged = kept.cost_pairs_held, kept.cost_pairs_judged
    return {
        "previous file": "; from the previous file",
        "too_few_pairs": f"; cost basis needs {needed} pairs with cost, {pairs_held} held",
        "too_few_judged": f"; cost basis needs {needed} gaps judged, {judged} held",
        "more_false_allows": "; cost basis not adopted: more false allows than flat",
        "no_fit": "; cost basis not adopted: no fit",
    }.get(kept.reason or "", "")


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
        wants_cost = getattr(limits, window).usage_estimate_basis == "cost"
        if kept is not None and cost_basis_in_force(window, kept, limits):
            hourly = f" + {kept.intercept_per_hour:g} points/h" if kept.intercept_per_hour else ""
            parts.append(
                f"{window} {kept.points_per_usd:.2f} points/${hourly} "
                f"({kept.cost_pairs_held} pairs with cost, scale {kept.safety_scale:g})"
            )
            calibrated.append(True)
            continue
        if kept is None or kept.quantile_pct_per_unit is None:
            held = 0 if kept is None else kept.pairs_available
            parts.append(f"{window} {applied}/unit default ({held} pairs of {needed} needed)")
            calibrated.append(False)
            continue
        raw = math.ceil(kept.quantile_pct_per_unit)
        mark = ", capped" if applied < raw else ", floor" if applied > raw else ""
        why = _why_flat(kept, limits) if wants_cost else ""
        parts.append(f"{window} {applied}/unit ({kept.pairs_used} pairs{mark}{why})")
        calibrated.append(True)
    if not any(calibrated):
        held = {found[w].pairs_available if w in found else 0 for w in WINDOWS}
        if len(held) == 1:
            return f"{head} defaults ({held.pop()} pairs of {needed} needed)"
    return f"{head} {', '.join(parts)}" + (", calibrated" if all(calibrated) else "")


ALLOWANCES_VERSION = 2


def read_allowances(path: Path) -> dict[str, Calibrated]:
    """The kept result; empty when the file is missing, unreadable, of a version this reader
    does not know or of another shape. A file of the previous shape, a calibration for each
    window name at the top level, is read as the flat calibration it was."""
    try:
        body = json.loads(path.read_text())
        if not isinstance(body, dict):
            return {}
        if "version" not in body:
            return {
                name: Calibrated.model_validate(each).model_copy(update={"reason": "previous file"})
                for name, each in body.items()
            }
        windows = body.get("windows")
        if body["version"] != ALLOWANCES_VERSION or not isinstance(windows, dict):
            return {}
        return {name: Calibrated.model_validate(each) for name, each in windows.items()}
    except (OSError, ValueError, ValidationError):
        return {}


def write_allowances(path: Path, found: Mapping[str, Calibrated]) -> None:
    """Keep `found` whole: a reader never sees half of it."""
    windows = {name: each.model_dump(mode="json") for name, each in found.items()}
    body = {"version": ALLOWANCES_VERSION, "windows": windows}
    atomic_write_text(path, json.dumps(body, indent=2))


def refresh_allowances(
    state_dir: Path,
    *,
    limits: ClaudeLimitsConfig,
    now: datetime,
    accounts: Sequence[claude_account.Account] = (),
) -> None:
    """Compute from the files in `state_dir` and keep the result, for the default account with
    `limits` and for each labelled account of `accounts` with its own limits, from its own call
    record and the units that ran on it. A result is left as it was when a file cannot be read
    or the result cannot be kept."""
    try:
        ledger = read_ledger(state_dir / LEDGER_NAME)
    except OSError:
        return
    for account in (None, *(each for each in accounts if each.label is not None)):
        held = account or claude_account.Account.default()
        try:
            try:
                calls = parse_calls(calls_path(state_dir, held).read_text())
            except FileNotFoundError:
                calls = []
            write_allowances(
                allowances_path(state_dir, held),
                calibrated_allowances(
                    calls,
                    ledger,
                    limits=limits if account is None else account.limits,
                    now=now,
                    account=account,
                ),
            )
        except OSError:
            continue
