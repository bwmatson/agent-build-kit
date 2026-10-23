"""What a unit is forecast to spend: its whole path when it starts, one step at a later gate and
what is still to come after some rounds of a step (spec: usage-pause)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from agent_build_kit.model import Frozen
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
    raise NotImplementedError


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
    raise NotImplementedError


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
    raise NotImplementedError
