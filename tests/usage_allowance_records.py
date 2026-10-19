"""Fabricated usage records for the allowance calibration: readings and the ledger beside them.

A segment is two good readings of one window two hours apart with the units that spent
between them; segments sit four hours apart, the next starting back at 10%, so a segment
is one usable pair and the step between two segments is a fall, which is not."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

from agent_build_kit.claude_account import Account
from agent_build_kit.pipeline.usage_allowances import Calibrated
from agent_build_kit.pipeline.usage_calls import UsageCall, calls_path
from agent_build_kit.pipeline.usage_ledger import LEDGER_NAME, UsageRecord, append_record

START = datetime(2026, 10, 1, 8, 0, tzinfo=UTC)
GAP = timedelta(hours=2)
STEP = timedelta(hours=4)
MIN_GAP = timedelta(minutes=15)
COMPUTED_AT = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)


def reading(window: str, at: datetime, pct: int | None, outcome: str = "ok") -> UsageCall:
    return UsageCall(
        at=at,
        caller="guard",
        outcome=outcome,
        status=200 if outcome == "ok" else None,
        session_pct=pct if window == "session" else None,
        weekly_pct=pct if window == "weekly" else None,
    )


def spend(unit: str, at: datetime, node: str = "implement") -> UsageRecord:
    return UsageRecord(at=at.isoformat(), unit=unit, node=node)


def gaps(
    window: str, spent: list[tuple[int, int, int]], *, start: datetime = START, gap: timedelta = GAP
) -> tuple[list[UsageCall], list[UsageRecord]]:
    """A (figure before, figure after, units that spent) gap for each entry, oldest first,
    laid out as `segments` lays out its own."""
    calls: list[UsageCall] = []
    ledger: list[UsageRecord] = []
    for index, (before, after, units) in enumerate(spent):
        first = start + index * STEP
        calls += [reading(window, first, before), reading(window, first + gap, after)]
        ledger += [spend(f"g{index}-{n}", first + gap / 2) for n in range(units)]
    return calls, ledger


def segments(
    window: str, spent: list[tuple[int, int]], *, start: datetime = START, gap: timedelta = GAP
) -> tuple[list[UsageCall], list[UsageRecord]]:
    """A (points gained, units that spent) segment for each entry, oldest first."""
    return gaps(window, [(10, 10 + gain, units) for gain, units in spent], start=start, gap=gap)


def per_unit(
    window: str, gains: Sequence[float], *, units: int = 2
) -> tuple[list[UsageCall], list[UsageRecord]]:
    """Segments whose gain per unit is each of `gains`, `units` spending in each."""
    return segments(window, [(round(each * units), units) for each in gains])


def keep(
    state_dir: Path,
    calls: list[UsageCall],
    ledger: list[UsageRecord],
    *,
    account: Account | None = None,
) -> None:
    """The record and the ledger as files in the state directory: the record where `account`'s
    calls are written (a labelled account has a file of its own), the ledger shared."""
    state_dir.mkdir(parents=True, exist_ok=True)
    calls_path(state_dir, account).write_text("".join(c.model_dump_json() + "\n" for c in calls))
    for record in ledger:
        append_record(state_dir / LEDGER_NAME, record)


def calibrated(raw: float | None, pairs: int = 24, *, at: datetime = COMPUTED_AT) -> Calibrated:
    """A kept calibration of one window: `raw` points a unit at the ninetieth, on `pairs`."""
    return Calibrated(
        quantile_pct_per_unit=raw,
        quantile=0.9,
        pairs_used=pairs,
        pairs_available=pairs,
        computed_at=at,
    )
