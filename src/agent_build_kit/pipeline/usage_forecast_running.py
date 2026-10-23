"""What the units running now are still expected to spend on their current step (spec:
usage-pause)."""

from __future__ import annotations

from collections.abc import Collection, Sequence
from datetime import datetime

from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.usage_forecast_record import StepRow
from agent_build_kit.pipeline.usage_ledger import UsageRecord


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
    raise NotImplementedError
