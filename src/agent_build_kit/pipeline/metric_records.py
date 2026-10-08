"""Local records of the pipeline's metrics, kept whether or not telemetry is on.

A record is a `metric` line of the usage ledger: the instrument's name, the
figure it was given and the attributes it carried, plus the unit and change it
belongs to (which an exported metric never carries). The archive roll-up leaves
these lines alone.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from agent_build_kit.model import Frozen


class MetricRecord(Frozen):
    """A `metric` line of the ledger."""

    kind: str = "metric"
    at: str
    metric: str
    value: float
    attributes: dict[str, str | int] = {}
    unit: str = ""
    change: str = ""


def record_metric(
    name: str,
    value: float,
    say: Callable[[str], None],
    *,
    unit: str = "",
    change: str = "",
    **attributes: str | int,
) -> None:
    """Append a record of `name` given `value`, never raising."""
    raise NotImplementedError


def read_metrics(ledger: Path) -> list[MetricRecord]:
    """The metric records of the ledger; a line that is not one is skipped."""
    raise NotImplementedError
