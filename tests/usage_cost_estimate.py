"""Fabricated state for the cost estimate: a kept reading, a ledger with costs and a kept
calibration with a cost fit, laid beside the guard's cache file (`tests/usage_host.py`)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from agent_build_kit.pipeline.usage_allowances import ALLOWANCES_NAME, Calibrated, write_allowances
from agent_build_kit.pipeline.usage_ledger import LEDGER_NAME, Cost, UsageRecord, append_record
from tests.usage_allowance_records import COMPUTED_AT
from tests.usage_host import Host, configure, payload, refused

MINUTE = timedelta(minutes=1)
HOUR = 60 * MINUTE
# Half a minute into the minute, so a test that runs for a second does not change the age shown.
OBSERVED_AGE = 54 * MINUTE + timedelta(seconds=30)


def cost_fit(
    points_per_usd: float,
    *,
    intercept: float | None = None,
    flat: float | None = 17,
    basis: str = "cost",
    reason: str | None = None,
) -> Calibrated:
    """A kept calibration of one window with a cost fit, `flat` points a unit beside it."""
    return Calibrated(
        quantile_pct_per_unit=flat,
        quantile=0.9,
        pairs_used=24,
        pairs_available=24,
        computed_at=COMPUTED_AT,
        basis=basis,  # type: ignore[arg-type]
        reason=reason,
        points_per_usd=points_per_usd,
        intercept_per_hour=intercept,
        safety_scale=1.0,
        cost_pairs_held=24,
        cost_pairs_judged=12,
        false_allows_cost=0,
        false_allows_flat=1,
    )


def keep_fits(host: Host, **found: Calibrated) -> None:
    write_allowances(host.cache.parent / ALLOWANCES_NAME, found)


def reading_at(host: Host) -> datetime:
    """When the reading kept in the cache was fetched."""
    return datetime.fromisoformat(json.loads(host.cache.read_text())["fetched_at"])


def paused(
    host: Host,
    *,
    age: timedelta = OBSERVED_AGE,
    session: float = 61.0,
    weekly: float = 6.0,
    session_resets_in: timedelta = timedelta(hours=2),
    **limits: object,
) -> None:
    """A reading `age` old with both thresholds at 80, the endpoint refusing and a climb fast
    enough that the reading alone leaves no headroom, so the start is decided on an estimate."""
    limits = {"usage_climb_floor": 2.0, **limits}
    configure(session={"usage_pause_pct": 80}, weekly={"usage_pause_pct": 80}, **limits)
    host.keep_reading(
        age, payload(session=session, weekly=weekly, session_resets_in=session_resets_in)
    )
    refused(host, cooling=3 * MINUTE)


def row(
    host: Host,
    node: str,
    cost: float | None,
    *,
    unit: str = "",
    ago: timedelta = 10 * MINUTE,
    at: datetime | None = None,
    round: int = 0,
    account: str | None = None,
) -> None:
    """The ledger holds a call of `node` costing `cost` dollars (none when None), `ago` before
    now or at `at`."""
    when = at if at is not None else datetime.now(UTC) - ago
    append_record(
        host.cache.parent / LEDGER_NAME,
        UsageRecord(
            at=when.isoformat(),
            unit=unit,
            node=node,
            round=round,
            session_id=f"{unit}-{node}-{round}-{when.isoformat()}",
            cost=Cost(incremental_usd=cost) if cost is not None else None,
            account=account,
        ),
    )


def admit(host: Host, *units: str) -> None:
    """The cache file records `units` as admitted on an estimate since the reading."""
    kept = json.loads(host.cache.read_text())
    host.cache.write_text(json.dumps({**kept, "estimate_units": list(units)}))
