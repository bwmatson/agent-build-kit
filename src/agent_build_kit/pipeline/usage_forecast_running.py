"""What the units running now are still expected to spend on their current step (spec:
usage-pause)."""

from __future__ import annotations

import statistics
from collections.abc import Collection, Sequence
from datetime import datetime

from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.usage_forecast_record import StepRow
from agent_build_kit.pipeline.usage_ledger import UsageRecord

# What a step past its mean duration still holds, as a share of its expected cost.
UNFINISHED_FLOOR = 0.1


class Remainder(Frozen):
    """The unfinished share of a running unit's step, in dollars and points."""

    unit: str
    node: str
    round: int
    usd: float
    points: float


class Remainders(Frozen):
    """The running units' remainders, and how many running units have no step row."""

    running: tuple[Remainder, ...]
    unrecorded: int


def running_remainders(
    steps: Sequence[StepRow],
    records: Sequence[UsageRecord],
    *,
    running: Collection[str],
    asking: str | None,
    now: datetime,
    points_per_usd: float,
) -> Remainders:
    """Each unit of `running` (but `asking`) whose latest step row has no ledger row of its unit,
    node and round at or after it adds the cell's mean cost, over every call of that node and
    round, times the greater of one less the share of the cell's mean duration elapsed and a
    tenth. A running unit with no step row adds nothing and is counted as unrecorded."""
    latest: dict[str, StepRow] = {}
    for step in sorted(steps, key=lambda s: s.at):
        latest[step.unit] = step
    others = [unit for unit in running if unit != asking]
    found = []
    for unit in others:
        if unit not in latest:
            continue
        step = latest[unit]
        if any(
            r.unit == unit
            and r.node == step.node
            and r.round == step.round
            and datetime.fromisoformat(r.at) >= step.at
            for r in records
        ):
            continue
        cell = [r for r in records if r.node == step.node and r.round == step.round]
        costs = [r.cost.incremental_usd for r in cell if r.cost and r.cost.incremental_usd]
        if not costs:
            continue
        durations = [r.duration_ms for r in cell if r.duration_ms]
        elapsed = (now - step.at).total_seconds() * 1000
        share = elapsed / statistics.fmean(durations) if durations else 0.0
        usd = statistics.fmean(costs) * max(1 - share, UNFINISHED_FLOOR)
        found.append(
            Remainder(
                unit=unit,
                node=step.node,
                round=step.round,
                usd=usd,
                points=usd * points_per_usd,
            )
        )
    return Remainders(
        running=tuple(found), unrecorded=sum(1 for unit in others if unit not in latest)
    )
