"""The forecast record: a forecast row when a unit's first step is admitted and a step row for
every step, in `usage-forecasts.jsonl` in the state directory (spec: usage-accounting)."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Literal

from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.usage_ledger import ledger_lock, read_lines
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
    forecasts: list[ForecastRow] = []
    steps: list[StepRow] = []
    for line in read_lines(path):
        try:
            body = json.loads(line)
            kind = body.get("kind") if isinstance(body, dict) else None
            if kind == "forecast":
                forecasts.append(ForecastRow.model_validate(body))
            elif kind == "step":
                steps.append(StepRow.model_validate(body))
        except ValueError:  # json and pydantic validation errors both
            continue
    return ForecastRecord(forecasts=tuple(forecasts), steps=tuple(steps))


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
    if not enabled:
        return
    try:
        with ledger_lock(path):
            record = read_record(path)
            rows: list[ForecastRow | StepRow] = []
            if forecast is not None and all(f.unit != forecast.unit for f in record.forecasts):
                rows.append(forecast)
            mine = [s for s in record.steps if s.unit == step.unit]
            if not mine or (mine[-1].node, mine[-1].round) != (step.node, step.round):
                rows.append(step)
            if rows:
                path.parent.mkdir(parents=True, exist_ok=True)
                # A line cut off by a crash would otherwise take the first new row with it.
                cut = (
                    path.exists()
                    and path.stat().st_size > 0
                    and not path.read_bytes().endswith(b"\n")
                )
                with path.open("a") as out:
                    out.write("\n" if cut else "")
                    out.write("".join(row.model_dump_json() + "\n" for row in rows))
    except OSError as error:
        say(f"the usage forecast record could not be written: {error}")
