"""Ledger rows and verdict records for the usage forecast's tests: units are made by the calls
they ran, and the tests read the forecast off them."""

from __future__ import annotations

from collections.abc import Iterable

from agent_build_kit.pipeline.usage_forecast_history import CellForecast, TierCells
from agent_build_kit.pipeline.usage_ledger import Cost, UsageRecord
from agent_build_kit.pipeline.verdict import ReviewTier
from agent_build_kit.pipeline.verdict_record import VerdictEntry

# The kind of test a row carries: never the review tier.
TEST_KIND = "unit-test"


def call(
    unit: str,
    node: str,
    round: int,
    usd: float,
    *,
    role: str | None = None,
    model: str | None = "model-a",
    kind: str = TEST_KIND,
    at: str = "2026-01-01T10:00:00+00:00",
    duration_ms: int | None = None,
) -> UsageRecord:
    """An agent row of `unit` for `node` and `round` costing `usd`; the role is the node's."""
    return UsageRecord(
        at=at,
        duration_ms=duration_ms,
        unit=unit,
        node=node,
        round=round,
        role=role or node,
        model=model,
        tier=kind,
        cost=Cost(incremental_usd=usd),
    )


def verdict(
    unit: str, planned: ReviewTier | None, *, final: bool = True, lines: int = 10
) -> VerdictEntry:
    """The verdict record of `unit`, planned as `planned`."""
    return VerdictEntry(
        unit=unit,
        change=unit.split("/")[0],
        round=1,
        final=final,
        unit_class="app/unit-test",
        planned_estimate=planned,
        classification=planned,
        drivers=(),
        evidence_tier=planned or ReviewTier.AUTO,
        tier=planned or ReviewTier.AUTO,
        reason="because",
        paths=(),
        lines=lines,
        brief=False,
    )


class Fixture:
    """Rows and verdict records built up one unit at a time."""

    def __init__(self) -> None:
        self.records: list[UsageRecord] = []
        self.verdicts: dict[str, VerdictEntry] = {}

    def unit(
        self,
        name: str,
        planned: ReviewTier | None,
        calls: Iterable[tuple[str, int, float]],
        *,
        final: bool = True,
        lines: int = 10,
        kind: str = TEST_KIND,
    ) -> str:
        """Add the unit `name` that ran `calls` of (node, round, usd) and has a verdict."""
        unit = f"{name}/1"
        self.records += [call(unit, n, r, usd, kind=kind) for n, r, usd in calls]
        self.verdicts[unit] = verdict(unit, planned, final=final, lines=lines)
        return unit

    def units(
        self,
        count: int,
        planned: ReviewTier | None,
        calls: Iterable[tuple[str, int, float]],
        lines: int = 10,
    ) -> None:
        """Add `count` units that each ran `calls`."""
        listed = list(calls)
        start = len(self.verdicts)
        for n in range(count):
            self.unit(f"u{start + n}", planned, listed, lines=lines)


def chance(found: TierCells, node: str, round: int) -> float:
    """The chance of the cell for `node` and `round`; 0 for a cell the history never ran."""
    return _cell(found, node, round).chance if _find(found, node, round) else 0.0


def cost(found: TierCells, node: str, round: int) -> float:
    return _cell(found, node, round).cost_usd


def _find(found: TierCells, node: str, round: int) -> list[CellForecast]:
    return [c for c in found.cells if c.cell.node == node and c.cell.round == round]


def _cell(found: TierCells, node: str, round: int) -> CellForecast:
    return _find(found, node, round)[0]


def spec_history() -> Fixture:
    """Twenty `auto` units that each ran tests ($0.80), implement ($0.60) and a review round 1
    ($1.00), six with a review round 2 ($0.50), and twenty `full` units that ran the same, of
    which eighteen ran a review round 2, six a round 3 ($0.40) and eighteen a rework round 0
    ($0.50)."""
    fixture = Fixture()
    base = [("tests", 0, 0.8), ("implement", 0, 0.6), ("review", 1, 1.0)]
    for n in range(20):
        extra = [("review", 2, 0.5)] if n < 6 else []
        fixture.unit(f"a{n}", ReviewTier.AUTO, base + extra)
    for n in range(20):
        extra = []
        if n < 18:
            extra += [("review", 2, 0.5), ("rework", 0, 0.5)]
        if n < 6:
            extra += [("review", 3, 0.4)]
        fixture.unit(f"f{n}", ReviewTier.FULL, base + extra)
    return fixture
