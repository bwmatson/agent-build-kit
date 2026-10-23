"""The forecast record: a forecast row when a unit's first step is admitted and a step row for
every step, in `usage-forecasts.jsonl` in the state directory (spec: usage-accounting)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Literal

from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.verdict import ReviewTier

FORECASTS_NAME = "usage-forecasts.jsonl"


class WindowForecast(Frozen):
    """A window's forecast: points, and the dollars they come from (none on the prior)."""

    usd: float | None
    points: float


class ForecastRow(Frozen):
    """What a unit was forecast to spend when its first step was admitted."""

    kind: Literal["forecast"] = "forecast"
    unit: str
    tier: ReviewTier | None
    band: str
    at: datetime
    session: WindowForecast
    weekly: WindowForecast
    parts: dict[str, float]
    prior: bool


class StepRow(Frozen):
    """An agent step the guard admitted."""

    kind: Literal["step"] = "step"
    unit: str
    node: str
    round: int
    at: datetime


class ForecastRecord(Frozen):
    """Every forecast row and step row that parses, in the order written."""

    forecasts: tuple[ForecastRow, ...]
    steps: tuple[StepRow, ...]


def read_record(path: Path) -> ForecastRecord:
    """The record's rows; a line that cannot be parsed is skipped, and no file is no rows."""
    raise NotImplementedError


def record_admission(
    path: Path,
    step: StepRow,
    forecast: ForecastRow | None,
    *,
    enabled: bool,
    say: Callable[[str], None],
) -> None:
    """Append `step`, once however often the same ask is made, and `forecast` when the unit has
    no forecast row, under the ledger's lock. Nothing is written when `enabled` is false, and a
    failure to write is said and not raised."""
    raise NotImplementedError
