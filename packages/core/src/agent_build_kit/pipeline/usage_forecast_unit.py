"""What a unit is forecast to spend: its whole path when it starts, one step at a later gate and
what is still to come after some rounds of a step (spec: usage-pause)."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Literal

from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.usage_forecast_history import TierCells, tier_cells
from agent_build_kit.pipeline.usage_ledger import UsageRecord
from agent_build_kit.pipeline.verdict import ReviewTier
from agent_build_kit.pipeline.verdict_record import VerdictEntry


class Part(Frozen):
    """The dollars one cell contributes to a forecast."""

    role: str
    node: str
    round: int
    usd: float


class UnitForecast(Frozen):
    """A forecast for one window: points, and the dollars by role and node they come from.
    On the prior the points are the window's flat allowance and there are no dollars or parts."""

    points: float
    usd: float | None
    prior: bool
    parts: tuple[Part, ...]
    # The size band of the tier's history the forecast was made from.
    band: Literal["all", "small", "large"] = "all"


def _forecast(
    records: Sequence[UsageRecord],
    verdicts: Mapping[str, VerdictEntry],
    pick: Callable[[TierCells], tuple[Part, ...] | None],
    *,
    tier: ReviewTier | None,
    estimated_lines: int | None,
    points_per_usd: float | None,
    flat_allowance: float,
    min_runs: int,
    quantile: float,
) -> UnitForecast:
    """The parts `pick` takes from the tier's cells, summed; the flat allowance on the prior,
    which `pick` asks for with None when the history has nothing for what is asked."""
    found = tier_cells(
        records,
        verdicts,
        tier=tier,
        estimated_lines=estimated_lines,
        points_per_usd=points_per_usd,
        min_runs=min_runs,
        quantile=quantile,
    )
    parts = None if found.prior or points_per_usd is None else pick(found)
    if parts is None or points_per_usd is None:
        return UnitForecast(points=flat_allowance, usd=None, prior=True, parts=(), band=found.band)
    usd = sum(p.usd for p in parts)
    return UnitForecast(
        points=usd * points_per_usd, usd=usd, prior=False, parts=parts, band=found.band
    )


def forecast_unit(
    records: Sequence[UsageRecord],
    verdicts: Mapping[str, VerdictEntry],
    *,
    tier: ReviewTier | None,
    estimated_lines: int | None,
    points_per_usd: float | None,
    flat_allowance: float,
    min_runs: int,
    quantile: float,
) -> UnitForecast:
    """A unit about to start: the sum over its tier's cells of chance times mean cost."""
    return _forecast(
        records,
        verdicts,
        lambda found: tuple(
            Part(role=c.cell.role, node=c.cell.node, round=c.cell.round, usd=c.chance * c.cost_usd)
            for c in found.cells
        ),
        tier=tier,
        estimated_lines=estimated_lines,
        points_per_usd=points_per_usd,
        flat_allowance=flat_allowance,
        min_runs=min_runs,
        quantile=quantile,
    )


def forecast_step(
    records: Sequence[UsageRecord],
    verdicts: Mapping[str, VerdictEntry],
    *,
    tier: ReviewTier | None,
    estimated_lines: int | None,
    node: str,
    round: int,
    points_per_usd: float | None,
    flat_allowance: float,
    min_runs: int,
    quantile: float,
) -> UnitForecast:
    """A later gate: the step of `node` and `round` once, at its mean cost over every model,
    whatever its chance. A step the tier never ran is the mean of its node, and a node it never
    ran is the prior."""

    def pick(found: TierCells) -> tuple[Part, ...] | None:
        steps = [s for s in found.steps if s.node == node and s.round == round]
        if steps:
            return tuple(
                Part(role=s.role or "", node=node, round=round, usd=s.cost_usd) for s in steps
            )
        mean = [n for n in found.nodes if n.node == node]
        if mean:
            return (Part(role="", node=node, round=round, usd=mean[0].cost_usd),)
        return None

    return _forecast(
        records,
        verdicts,
        pick,
        tier=tier,
        estimated_lines=estimated_lines,
        points_per_usd=points_per_usd,
        flat_allowance=flat_allowance,
        min_runs=min_runs,
        quantile=quantile,
    )


def forecast_remaining(
    records: Sequence[UsageRecord],
    verdicts: Mapping[str, VerdictEntry],
    *,
    tier: ReviewTier | None,
    estimated_lines: int | None,
    node: str,
    last_round: int,
    points_per_usd: float | None,
    flat_allowance: float,
    min_runs: int,
    quantile: float,
) -> UnitForecast:
    """What is still to come of `node` for a unit whose last round of it was `last_round` (the
    round's own number, so 0 for a node numbered from 0): each later round's cost at its chance
    given the unit got this far. Nothing is to come past the last round the tier recorded, and a
    node the tier never ran is the prior."""

    def pick(found: TierCells) -> tuple[Part, ...] | None:
        cells = [c for c in found.cells if c.cell.node == node]
        if not cells:
            return None
        reached = min(sum(c.chance for c in cells if c.cell.round == last_round), 1.0)
        if reached == 0 and last_round >= min(c.cell.round for c in cells):
            return ()
        reached = reached or 1.0
        return tuple(
            Part(
                role=c.cell.role,
                node=node,
                round=c.cell.round,
                usd=c.chance / reached * c.cost_usd,
            )
            for c in cells
            if c.cell.round > last_round
        )

    return _forecast(
        records,
        verdicts,
        pick,
        tier=tier,
        estimated_lines=estimated_lines,
        points_per_usd=points_per_usd,
        flat_allowance=flat_allowance,
        min_runs=min_runs,
        quantile=quantile,
    )
