"""Local records of the pipeline's metrics, kept whether or not telemetry is on.

A record is a `metric` line of the usage ledger: the instrument's name, the
figure it was given and the attributes it carried, plus the unit and change it
belongs to (which an exported metric never carries). The archive roll-up leaves
these lines alone.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import ValidationError, field_validator

from agent_build_kit import telemetry
from agent_build_kit.compat_names import Place, new_spelling
from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.usage_ledger import read_lines, record_line

InstrumentKind = Literal["count", "duration", "observe", "level"]


class MetricRecord(Frozen):
    """A `metric` line of the ledger."""

    kind: str = "metric"
    at: str
    metric: str
    value: float
    attributes: dict[str, str | int] = {}
    unit: str = ""
    change: str = ""

    @field_validator("attributes", mode="after")
    @classmethod
    def _read_old_kind(cls, attributes: dict[str, str | int]) -> dict[str, str | int]:
        """A line written before the rename holds the old spelling of its kind as its `tier`."""
        kind = attributes.get("tier")
        if isinstance(kind, str):
            return {**attributes, "tier": new_spelling(Place.VALUE, kind)}
        return attributes


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
    try:
        record = MetricRecord(
            at=datetime.now(UTC).isoformat(),
            metric=name,
            value=value,
            attributes=attributes,
            unit=unit,
            change=change,
        )
    except ValidationError as error:
        say(f"a metric record could not be made ({error})")
        return
    record_line(record, say)


def emit_metric(
    instrument: InstrumentKind,
    name: str,
    value: float,
    say: Callable[[str], None],
    /,
    *,
    unit: str = "",
    change: str = "",
    **attributes: str | int,
) -> None:
    """Send `value` to telemetry as the `instrument` (`count`, `duration`,
    `observe` or `level`) `name`, and append the same figure as a local record."""
    getattr(telemetry, instrument)(name, value, **attributes)
    record_metric(name, value, say, unit=unit, change=change, **attributes)


def read_metrics(ledger: Path) -> list[MetricRecord]:
    """The metric records of the ledger; a line that is not one is skipped."""
    found = []
    for line in read_lines(ledger):
        try:
            raw = json.loads(line)
            if raw.get("kind") == "metric":
                found.append(MetricRecord.model_validate(raw))
        except (ValueError, AttributeError, ValidationError):
            continue
    return found
