"""What one ask of the start decision is forecast to cost in a window, and what dominates it: the
unit's own cost (its whole path at a start, the step asked at a later gate, one call at its mean
for a track or the plan), the running units' remainders and the reservations (spec: usage-pause)."""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from datetime import datetime

from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.usage_forecast_record import StepRow
from agent_build_kit.pipeline.usage_forecast_reservations import TimerReading, reserve
from agent_build_kit.pipeline.usage_forecast_running import mean_cost, running_remainders
from agent_build_kit.pipeline.usage_forecast_unit import (
    Part,
    UnitForecast,
    forecast_step,
    forecast_unit,
)
from agent_build_kit.pipeline.usage_ledger import UsageRecord
from agent_build_kit.pipeline.verdict import ReviewTier
from agent_build_kit.pipeline.verdict_record import VerdictEntry
from agent_build_kit.pipeline.vocabulary import OverheadNode

_OVERHEAD = frozenset(node.value for node in OverheadNode)


class Ask(Frozen):
    """What the guard is told of a start: the unit (or `track:<phase>`), its review tier and
    estimated lines, and the step and round it is for."""

    unit: str | None = None
    tier: ReviewTier | None = None
    lines: int | None = None
    step: str | None = None
    step_round: int | None = None

    @property
    def forecast(self) -> bool:
        """Whether there is anything to forecast: a review tier or estimated lines are given
        (a gate names a unit's, whether or not it has a tier) or the step is a call outside a
        unit's graph. A start that names only a unit has nothing to forecast from."""
        return self.tier is not None or self.lines is not None or self.step in _OVERHEAD


class Contribution(Frozen):
    """What one part of a forecast holds, in points."""

    label: str
    points: float


class AskForecast(Frozen):
    """The points an ask is forecast to need in one window, the parts they come from and whether
    the unit's own part is the window's flat allowance for want of history."""

    subject: str
    points: float
    prior: bool
    parts: tuple[Contribution, ...]

    @property
    def largest(self) -> Contribution | None:
        if not self.parts:
            return None
        return max(self.parts, key=lambda part: part.points)

    def text(self, window: str) -> str:
        """The forecast in words, naming the window and the part with the most points."""
        said = f"{self.subject} forecast {self.points:.1f}% {window}"
        if self.prior:
            said += " (the prior: too little history)"
        largest = self.largest
        if largest is not None:
            said += f": {largest.label} {largest.points:.1f}% is the largest"
        return said


def _label(part: Part) -> str:
    named = part.node if part.role in ("", part.node) else f"{part.role} {part.node}"
    return f"{named} round {part.round}"


def forecast_ask(
    ask: Ask,
    *,
    records: Sequence[UsageRecord],
    verdicts: Mapping[str, VerdictEntry],
    steps: Sequence[StepRow],
    timers: TimerReading,
    now: datetime,
    resets_at: datetime | None,
    points_per_usd: float | None,
    flat_allowance: float,
    min_runs: int,
    quantile: float,
    counted: Collection[str] = (),
    admitted: bool = False,
) -> AskForecast:
    """The forecast of `ask` for one window. `counted` are the running units the window's
    estimate already holds the remainder of, and `admitted` says the asking unit was admitted on
    the estimate, so this is a later gate of it."""
    parts: list[Contribution] = []
    prior = False
    if ask.step in _OVERHEAD:
        usd = mean_cost(records, ask.step)
        prior = usd is None or points_per_usd is None
        points = flat_allowance if usd is None or points_per_usd is None else usd * points_per_usd
        parts.append(Contribution(label=ask.step, points=points))
    elif ask.unit is not None or ask.tier is not None:
        later = admitted or (ask.unit is not None and any(s.unit == ask.unit for s in steps))
        own: UnitForecast | None
        if later and (ask.step is None or ask.step_round is None):
            # Asked for no step: what the unit admitted is expected to spend is in the estimate.
            own = None
        elif later and ask.step is not None and ask.step_round is not None:
            own = forecast_step(
                records,
                verdicts,
                tier=ask.tier,
                estimated_lines=ask.lines,
                node=ask.step,
                round=ask.step_round,
                points_per_usd=points_per_usd,
                flat_allowance=flat_allowance,
                min_runs=min_runs,
                quantile=quantile,
            )
        else:
            own = forecast_unit(
                records,
                verdicts,
                tier=ask.tier,
                estimated_lines=ask.lines,
                points_per_usd=points_per_usd,
                flat_allowance=flat_allowance,
                min_runs=min_runs,
                quantile=quantile,
            )
        if own is not None and own.prior and admitted:
            # The estimate holds an admitted unit at the flat allowance already.
            own = None
        if own is not None:
            prior = own.prior
            if own.prior:
                parts.append(Contribution(label="the flat allowance", points=own.points))
            factor = points_per_usd or 0.0
            parts += [Contribution(label=_label(p), points=p.usd * factor) for p in own.parts]
    if points_per_usd is not None:
        running = {s.unit for s in steps} - set(counted)
        found = running_remainders(
            steps, records, running=running, asking=ask.unit, now=now, points_per_usd=points_per_usd
        )
        parts += [
            Contribution(label=f"unit {r.unit} running {r.node} round {r.round}", points=r.points)
            for r in found.running
        ]
        if resets_at is not None:
            reserved = reserve(
                records,
                timers,
                plan_due=False,
                proposing=(),
                resets_at=resets_at,
                now=now,
                points_per_usd=points_per_usd,
            )
            parts += [
                Contribution(label=f"{r.name} reservation", points=r.points)
                for r in reserved.items
                if r.name != ask.step
            ]
    subject = f"unit {ask.unit}" if ask.unit else (ask.step or "start")
    if ask.tier is not None:
        subject += f" ({ask.tier})"
    return AskForecast(
        subject=subject, points=sum(p.points for p in parts), prior=prior, parts=tuple(parts)
    )
