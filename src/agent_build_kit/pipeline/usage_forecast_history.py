"""The recorded history of a review tier and the chance and cost of each of its cells, which
a unit's forecast is summed over (spec: usage-pause)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Literal

from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.usage_ledger import UsageRecord
from agent_build_kit.pipeline.verdict import ReviewTier
from agent_build_kit.pipeline.verdict_record import VerdictEntry


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


def gather_history(
    records: Sequence[UsageRecord], verdicts: Mapping[str, VerdictEntry], tier: ReviewTier
) -> TierHistory:
    """The units whose verdict record is final and planned `tier`, each with its agent calls
    by unit id. Overhead rows and units with no final verdict are left out."""
    raise NotImplementedError


def reach_rate(reached: int, units: int, quantile: float) -> float:
    """The chance of a cell reached by `reached` of `units`: the share plus z(quantile)
    standard errors of the smoothed share, at most 1."""
    raise NotImplementedError


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
    raise NotImplementedError
