"""The recorded history of a review tier and the chance and cost of each of its cells, which
a unit's forecast is summed over (spec: usage-pause)."""

from __future__ import annotations

import math
import statistics
from collections import defaultdict
from collections.abc import Mapping, Sequence
from statistics import NormalDist
from typing import Literal

from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.usage_ledger import UsageRecord
from agent_build_kit.pipeline.verdict import ReviewTier
from agent_build_kit.pipeline.verdict_record import VerdictEntry
from agent_build_kit.pipeline.vocabulary import OverheadNode


class Cell(Frozen):
    """A role, node, round and model: what a forecast is summed over."""

    role: str
    node: str
    round: int
    model: str | None


class UnitRuns(Frozen):
    """A unit of a tier's history: its changed lines and every agent call it made."""

    unit: str
    lines: int
    calls: tuple[UsageRecord, ...]


class TierHistory(Frozen):
    """The units whose final verdict record planned a tier."""

    tier: ReviewTier
    units: tuple[UnitRuns, ...]


class CellForecast(Frozen):
    """A cell's chance of being reached and its mean cost in dollars."""

    cell: Cell
    chance: float
    cost_usd: float


class TierCells(Frozen):
    """What a unit of a tier is forecast from: its cells, the units they rest on and the size
    band used, or `prior` when the flat allowance stands in and `cells` is empty."""

    prior: bool
    units: int
    band: Literal["all", "small", "large"]
    cells: tuple[CellForecast, ...]


_OVERHEAD = frozenset(node.value for node in OverheadNode)


def gather_history(
    records: Sequence[UsageRecord], verdicts: Mapping[str, VerdictEntry], tier: ReviewTier
) -> TierHistory:
    """The units whose verdict record is final and planned `tier`, each with its agent calls
    by unit id. Overhead rows and units with no final verdict are left out."""
    calls: dict[str, list[UsageRecord]] = defaultdict(list)
    for record in records:
        entry = verdicts.get(record.unit)
        if (
            record.kind == "agent"
            and record.node not in _OVERHEAD
            and entry is not None
            and entry.final
            and entry.planned_estimate == tier
            and record.cost is not None
            and record.cost.incremental_usd is not None
        ):
            calls[record.unit].append(record)
    units = tuple(
        UnitRuns(unit=unit, lines=verdicts[unit].lines, calls=tuple(rows))
        for unit, rows in calls.items()
    )
    return TierHistory(tier=tier, units=units)


def reach_rate(reached: int, units: int, quantile: float) -> float:
    """The chance of a cell reached by `reached` of `units`: the share plus z(quantile)
    standard errors of the smoothed share, at most 1."""
    if quantile >= 1:
        return 1.0
    share = reached / units
    smoothed = (reached + 1) / (units + 2)
    error = math.sqrt(smoothed * (1 - smoothed) / units)
    return min(share + NormalDist().inv_cdf(quantile) * error, 1.0)


def tier_cells(
    records: Sequence[UsageRecord],
    verdicts: Mapping[str, VerdictEntry],
    *,
    tier: ReviewTier | None,
    estimated_lines: int | None,
    points_per_usd: float | None,
    min_runs: int,
    quantile: float,
) -> TierCells:
    """The cells a unit of `tier` is forecast from, or the prior when the tier is unknown, has
    fewer than `min_runs` units or the window has no `points_per_usd`."""
    if tier is None or points_per_usd is None:
        return TierCells(prior=True, units=0, band="all", cells=())
    units = gather_history(records, verdicts, tier).units
    if len(units) < min_runs:
        return TierCells(prior=True, units=len(units), band="all", cells=())
    band, units = _band(units, estimated_lines, min_runs)
    return TierCells(
        prior=False, units=len(units), band=band, cells=_cells(units, min_runs, quantile)
    )


def _band(
    units: tuple[UnitRuns, ...], estimated_lines: int | None, min_runs: int
) -> tuple[Literal["all", "small", "large"], tuple[UnitRuns, ...]]:
    """The size band of the tier's units an estimate falls in, when each band is big enough."""
    if estimated_lines is None:
        return "all", units
    median = statistics.median(u.lines for u in units)
    small = tuple(u for u in units if u.lines <= median)
    large = tuple(u for u in units if u.lines > median)
    if len(small) < min_runs or len(large) < min_runs:
        return "all", units
    return ("small", small) if estimated_lines <= median else ("large", large)


def _cells(units: tuple[UnitRuns, ...], min_runs: int, quantile: float) -> tuple[CellForecast, ...]:
    """Each cell the units ran, with its chance (not rising with the round within a step) and
    its mean cost, widened to the role, node and round and then the node when thin."""
    by_cell: dict[Cell, list[float]] = defaultdict(list)
    reached: dict[Cell, set[str]] = defaultdict(set)
    for unit in units:
        for call in unit.calls:
            cell = Cell(role=call.role, node=call.node, round=call.round, model=call.model)
            by_cell[cell].append(_usd(call))
            reached[cell].add(unit.unit)
    chances = {c: reach_rate(len(u), len(units), quantile) for c, u in reached.items()}
    ceilings: dict[tuple[str, str, str | None], float] = {}
    for cell in sorted(chances, key=lambda c: c.round):
        step = (cell.role, cell.node, cell.model)
        chances[cell] = ceilings[step] = min(chances[cell], ceilings.get(step, 1.0))

    def mean(match: Mapping[Cell, list[float]]) -> list[float]:
        return [usd for costs in match.values() for usd in costs]

    def cost(cell: Cell) -> float:
        own = by_cell[cell]
        if len(own) >= min_runs:
            return statistics.fmean(own)
        same_round = mean({c: v for c, v in by_cell.items() if _round(c) == _round(cell)})
        if len(same_round) >= min_runs:
            return statistics.fmean(same_round)
        return statistics.fmean(mean({c: v for c, v in by_cell.items() if c.node == cell.node}))

    return tuple(
        CellForecast(cell=cell, chance=chances[cell], cost_usd=cost(cell))
        for cell in sorted(by_cell, key=lambda c: (c.node, c.round, c.model or ""))
    )


def _round(cell: Cell) -> tuple[str, str, int]:
    return cell.role, cell.node, cell.round


def _usd(call: UsageRecord) -> float:
    assert call.cost is not None and call.cost.incremental_usd is not None
    return call.cost.incremental_usd
