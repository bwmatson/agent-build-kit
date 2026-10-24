"""The `forecast:` line of `abk status`: what a unit of each review tier is forecast to need in
each window, the running units' remainders and the reservations (spec: usage-pause)."""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from datetime import datetime

from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.usage_forecast_ask import PROPOSING_TRACKS
from agent_build_kit.pipeline.usage_forecast_history import gather_history
from agent_build_kit.pipeline.usage_forecast_record import StepRow
from agent_build_kit.pipeline.usage_forecast_reservations import TimerReading, reserve
from agent_build_kit.pipeline.usage_forecast_running import running_remainders
from agent_build_kit.pipeline.usage_forecast_unit import forecast_unit
from agent_build_kit.pipeline.usage_ledger import UsageRecord
from agent_build_kit.pipeline.verdict import ReviewTier
from agent_build_kit.pipeline.verdict_record import VerdictEntry


class WindowFacts(Frozen):
    """One window as the line needs it: when it resets, its points a dollar when it has a cost
    basis in force, and its flat per-unit allowance."""

    name: str
    resets_at: datetime | None
    points_per_usd: float | None
    flat_allowance: float


def forecast_line(
    windows: Sequence[WindowFacts],
    *,
    records: Sequence[UsageRecord],
    verdicts: Mapping[str, VerdictEntry],
    steps: Sequence[StepRow],
    timers: TimerReading,
    running: Collection[str],
    now: datetime,
    min_runs: int,
    quantile: float,
) -> str:
    """`forecast: ` and, for each window, each tier's points with the units its history rests
    on or `prior`, then the running units' remaining points and the reservations; the units
    running with no step row and whether the timers were read follow."""
    parts = []
    # What a tier's history rests on and which running units have no step row do not depend on
    # the window, so they are worked out once.
    units = {tier: len(gather_history(records, verdicts, tier).units) for tier in ReviewTier}
    stepped = {step.unit for step in steps}
    unrecorded = sum(1 for unit in running if unit not in stepped)
    for window in windows:
        tiers = []
        for tier in ReviewTier:
            found = forecast_unit(
                records,
                verdicts,
                tier=tier,
                estimated_lines=None,
                points_per_usd=window.points_per_usd,
                flat_allowance=window.flat_allowance,
                min_runs=min_runs,
                quantile=quantile,
            )
            said = "prior" if found.prior else f"({units[tier]} units)"
            tiers.append(f"{tier.value} {found.points:.1f}% {said}")
        text = f"{window.name} {', '.join(tiers)}"
        if window.points_per_usd is not None:
            remainders = running_remainders(
                steps,
                records,
                running=running,
                asking=None,
                now=now,
                points_per_usd=window.points_per_usd,
            )
            held = [f"{r.unit} {r.points:.1f}%" for r in remainders.running]
            if window.resets_at is not None:
                reserved = reserve(
                    records,
                    timers,
                    plan_due=False,
                    proposing=PROPOSING_TRACKS,
                    resets_at=window.resets_at,
                    now=now,
                    points_per_usd=window.points_per_usd,
                )
                held_back = [f"{r.name} {r.points:.1f}%" for r in reserved.items]
            else:
                held_back = []
            if held:
                text += f"; running {', '.join(held)}"
            if held_back:
                text += f"; reserved {', '.join(held_back)}"
        parts.append(text)
    tail = [f"{unrecorded} unrecorded"] if unrecorded else []
    tail.append("timers read" if timers.read else "timers not read")
    return f"forecast: {' | '.join(parts)}; {'; '.join(tail)}"
