"""What a unit is forecast to spend: its whole path when it starts, one step at a later gate and
what is still to come after some rounds of a step (spec: usage-pause)."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence

from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.usage_forecast_history import CellForecast, tier_cells
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


def _forecast(
    records: Sequence[UsageRecord],
    verdicts: Mapping[str, VerdictEntry],
    pick: Callable[[tuple[CellForecast, ...]], list[tuple[CellForecast, float]]],
    *,
    tier: ReviewTier | None,
    estimated_lines: int | None,
    points_per_usd: float | None,
    flat_allowance: float,
    min_runs: int,
    quantile: float,
) -> UnitForecast:
    """The cells `pick` weights, summed; the flat allowance on the prior."""
    found = tier_cells(
        records,
        verdicts,
        tier=tier,
        estimated_lines=estimated_lines,
        points_per_usd=points_per_usd,
        min_runs=min_runs,
        quantile=quantile,
    )
    if found.prior or points_per_usd is None:
        return UnitForecast(points=flat_allowance, usd=None, prior=True, parts=())
    parts = tuple(
        Part(role=c.cell.role, node=c.cell.node, round=c.cell.round, usd=weight * c.cost_usd)
        for c, weight in pick(found.cells)
    )
    usd = sum(p.usd for p in parts)
    return UnitForecast(points=usd * points_per_usd, usd=usd, prior=False, parts=parts)


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
        lambda cells: [(c, c.chance) for c in cells],
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
    """A later gate: the cell of `node` and `round` at its mean cost, whatever its chance."""
    return _forecast(
        records,
        verdicts,
        lambda cells: [(c, 1.0) for c in cells if c.cell.node == node and c.cell.round == round],
        tier=tier,
        estimated_lines=estimated_lines,
        points_per_usd=points_per_usd,
        flat_allowance=flat_allowance,
        min_runs=min_runs,
        quantile=quantile,
    )


def _reach(cells: Sequence[CellForecast], node: str, round: int) -> float:
    return min(sum(c.chance for c in cells if c.cell.node == node and c.cell.round == round), 1.0)


def forecast_remaining(
    records: Sequence[UsageRecord],
    verdicts: Mapping[str, VerdictEntry],
    *,
    tier: ReviewTier | None,
    estimated_lines: int | None,
    node: str,
    rounds_run: int,
    points_per_usd: float | None,
    flat_allowance: float,
    min_runs: int,
    quantile: float,
) -> UnitForecast:
    """What is still to come of `node` for a unit that has run `rounds_run` rounds of it: each
    later round's cost at its chance given the unit got this far."""

    def pick(cells: tuple[CellForecast, ...]) -> list[tuple[CellForecast, float]]:
        reached = _reach(cells, node, rounds_run)
        if reached == 0:
            return []
        return [
            (c, c.chance / reached)
            for c in cells
            if c.cell.node == node and c.cell.round > rounds_run
        ]

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
