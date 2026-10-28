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


class StepCost(Frozen):
    """The mean cost of a role, node and round over every model, widened to the node's mean
    when the step has fewer calls than the minimum; `node` alone is a node's mean (`round`
    and `role` are then empty)."""

    role: str | None
    node: str
    round: int | None
    cost_usd: float


class TierCells(Frozen):
    """What a unit of a tier is forecast from: its cells, the units they rest on and the size
    band used, or `prior` when the flat allowance stands in and `cells` is empty."""

    prior: bool
    units: int
    band: Literal["all", "small", "large"]
    cells: tuple[CellForecast, ...]
    steps: tuple[StepCost, ...] = ()
    nodes: tuple[StepCost, ...] = ()


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
    cells, steps, nodes = _cells(units, min_runs, quantile)
    return TierCells(
        prior=False, units=len(units), band=band, cells=cells, steps=steps, nodes=nodes
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


def _cells(
    units: tuple[UnitRuns, ...], min_runs: int, quantile: float
) -> tuple[tuple[CellForecast, ...], tuple[StepCost, ...], tuple[StepCost, ...]]:
    """Each cell the units ran with its chance and mean cost, and the all-model mean of each
    step and of each node. A step's total chance over its models does not rise with the round;
    a cell or step with fewer calls than the minimum takes the wider mean."""
    by_cell: dict[Cell, list[float]] = defaultdict(list)
    reached: dict[Cell, set[str]] = defaultdict(set)
    for unit in units:
        for call in unit.calls:
            cell = Cell(
                role=call.role,
                node=call.node,
                round=call.round,
                model=call.model or call.reported_model,
            )
            by_cell[cell].append(_usd(call))
            reached[cell].add(unit.unit)
    chances = {c: reach_rate(len(u), len(units), quantile) for c, u in reached.items()}
    _cap_rounds(chances)

    by_step: dict[tuple[str, str, int], list[float]] = defaultdict(list)
    by_node: dict[str, list[float]] = defaultdict(list)
    for cell, costs in by_cell.items():
        by_step[(cell.role, cell.node, cell.round)] += costs
        by_node[cell.node] += costs

    def step_cost(role: str, node: str, round: int) -> float:
        own = by_step[(role, node, round)]
        return statistics.fmean(own if len(own) >= min_runs else by_node[node])

    def cost(cell: Cell) -> float:
        own = by_cell[cell]
        if len(own) >= min_runs:
            return statistics.fmean(own)
        return step_cost(cell.role, cell.node, cell.round)

    cells = tuple(
        CellForecast(cell=cell, chance=chances[cell], cost_usd=cost(cell))
        for cell in sorted(by_cell, key=lambda c: (c.node, c.round, c.model or ""))
    )
    steps = tuple(
        StepCost(role=r, node=n, round=k, cost_usd=step_cost(r, n, k))
        for r, n, k in sorted(by_step, key=lambda t: (t[1], t[2], t[0]))
    )
    nodes = tuple(
        StepCost(role=None, node=n, round=None, cost_usd=statistics.fmean(v))
        for n, v in sorted(by_node.items())
    )
    return cells, steps, nodes


def _cap_rounds(chances: dict[Cell, float]) -> None:
    """Scale the cells of a round down so that a step's total chance over its models is at most
    the previous round's, a unit reaching a round having reached the one before."""
    rounds: dict[tuple[str, str], dict[int, list[Cell]]] = defaultdict(lambda: defaultdict(list))
    for cell in chances:
        rounds[(cell.role, cell.node)][cell.round].append(cell)
    for by_round in rounds.values():
        ceiling = 1.0
        for round in sorted(by_round):
            total = sum(chances[c] for c in by_round[round])
            allowed = min(total, ceiling)
            if total > allowed:
                for c in by_round[round]:
                    chances[c] *= allowed / total
            ceiling = allowed


def _usd(call: UsageRecord) -> float:
    assert call.cost is not None and call.cost.incremental_usd is not None
    return call.cost.incremental_usd
