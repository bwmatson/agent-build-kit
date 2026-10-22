"""Fabricated readings and ledger rows with a recorded cost, for the cost fit.

A gap is two good readings of one window `hours` apart with the rows recorded between them:
one row for each of its units, or a single unit-less `plan` row for none. Gaps sit four hours
apart, so the step from one gap's later reading to the next gap's earlier one is a fall (or,
for a gap that gained nothing, a pair with no row in it), and a gap lasts less than that."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime, timedelta

from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.usage_calls import UsageCall
from agent_build_kit.pipeline.usage_ledger import Cost, UsageRecord
from tests.usage_allowance_records import START, STEP, reading


class Gap(Frozen):
    """One gap: the figure before, the points gained, the cost recorded in it and how it was
    spent: by `units` units, or by a unit-less `plan` row when there are none."""

    before: int = 10
    gain: int
    cost: float | None
    hours: float = 2.0
    units: int = 1


def row(
    at: datetime, *, unit: str, node: str, cost: float | None, account: str | None = None
) -> UsageRecord:
    return UsageRecord(
        at=at.isoformat(),
        unit=unit,
        node=node,
        cost=None if cost is None else Cost(incremental_usd=cost),
        account=account,
    )


def cost_gaps(
    window: str,
    gaps: Sequence[Gap],
    *,
    start: datetime = START,
    account: str | None = None,
) -> tuple[list[UsageCall], list[UsageRecord]]:
    """The readings and the rows of each gap, oldest first, the cost of a gap shared equally by
    its units. `account` is the account directory the readings and the rows carry."""
    calls: list[UsageCall] = []
    ledger: list[UsageRecord] = []
    for index, gap in enumerate(gaps):
        first = start + index * STEP
        later = first + timedelta(hours=gap.hours)
        mid = first + timedelta(hours=gap.hours / 2)
        calls += [
            reading(window, first, gap.before).model_copy(update={"account": account}),
            reading(window, later, gap.before + gap.gain).model_copy(update={"account": account}),
        ]
        if gap.units == 0:
            ledger.append(row(mid, unit="", node="plan", cost=gap.cost, account=account))
            continue
        each = None if gap.cost is None else gap.cost / gap.units
        ledger += [
            row(mid, unit=f"g{index}-{n}", node="review", cost=each, account=account)
            for n in range(gap.units)
        ]
    return calls, ledger


def varied(
    count: int,
    gain: Callable[[float, float, int], float],
    *,
    costs: Sequence[float] = (1.0, 2.0, 3.0, 4.0),
    hours: Sequence[float] = (1.0, 1.5, 2.0, 2.5, 3.0),
    before: int = 10,
) -> list[Gap]:
    """`count` one-unit gaps whose cost and length cycle through `costs` and `hours`, of
    different periods so that the two are not a function of each other, and whose gain is
    `gain(cost, hours, index)`."""
    made = []
    for index in range(count):
        spent, long = costs[index % len(costs)], hours[index % len(hours)]
        made.append(
            Gap(before=before, gain=round(gain(spent, long, index)), cost=spent, hours=long)
        )
    return made
