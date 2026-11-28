"""The health thresholds: which of them a report breaches, and the correction each names."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta

from agent_build_kit.config import HealthConfig
from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.trusted_cost import TrustedChanges, Verdict
from agent_build_kit.pipeline.unit_store import StoredUnit
from agent_build_kit.pipeline.units import UnitState
from agent_build_kit.pipeline.usage_report import DaySpend

_WEEK_DAYS = 7


class Breach(Frozen):
    """A threshold crossed: its signal, what was observed, its limit and correction, and the
    evidence a person reads."""

    signal: str
    observed: float
    limit: float
    correction: str
    evidence: tuple[str, ...] = ()


class ThresholdReport(Frozen):
    breaches: tuple[Breach, ...] = ()
    # The windows (`latest`, `previous`) that had no costed trusted change.
    lacking: tuple[str, ...] = ()


def evaluate_thresholds(
    days: Sequence[DaySpend],
    trusted: TrustedChanges,
    units: Sequence[StoredUnit],
    health: HealthConfig,
    *,
    now: datetime,
) -> ThresholdReport:
    """Each breached threshold at `now`, and the windows that lacked a costed trusted change."""
    cost_breaches, lacking = _cost_rise(trusted, health)
    return ThresholdReport(
        breaches=(
            *_plan_review_share(days, health, now),
            *cost_breaches,
            *_unit_failure_rate(units, health, now),
        ),
        lacking=lacking,
    )


def _plan_review_share(
    days: Sequence[DaySpend], health: HealthConfig, now: datetime
) -> list[Breach]:
    row = health.thresholds.plan_review_share
    first = (now - timedelta(days=_WEEK_DAYS - 1)).date().isoformat()
    found = []
    for day in days:
        if day.day < first or day.day > now.date().isoformat() or day.total <= 0:
            continue
        plan = day.by_role.get("plan", 0.0)
        if plan / day.total > row.limit:
            found.append(
                Breach(
                    signal="plan_review_share",
                    observed=plan / day.total,
                    limit=row.limit,
                    correction=row.correction,
                    evidence=(f"{day.day}: plan {plan:.2f} USD of {day.total:.2f} USD",),
                )
            )
    return found


def _cost_rise(
    trusted: TrustedChanges, health: HealthConfig
) -> tuple[list[Breach], tuple[str, ...]]:
    latest, previous = (
        trusted.latest.cost_per_trusted_change,
        trusted.previous.cost_per_trusted_change,
    )
    lacking = tuple(
        name for name, figure in (("latest", latest), ("previous", previous)) if figure is None
    )
    if latest is None or previous is None or previous <= 0:
        return [], lacking
    row = health.thresholds.cost_per_trusted_change
    rise = (latest - previous) / previous
    if rise <= row.limit:
        return [], lacking
    # The latest window's trusted changes are the most recently merged costed ones.
    costed = sorted(
        (c for c in trusted.changes if c.verdict == Verdict.TRUSTED and c.cost is not None),
        key=lambda c: c.merged_at,
        reverse=True,
    )[: trusted.latest.costed]
    top = sorted(costed, key=lambda c: c.cost or 0.0, reverse=True)[: health.top]
    return [
        Breach(
            signal="cost_per_trusted_change",
            observed=rise,
            limit=row.limit,
            correction=row.correction,
            evidence=tuple(f"{c.change}: {c.cost or 0.0:.2f} USD" for c in top),
        )
    ], lacking


def _unit_failure_rate(
    units: Sequence[StoredUnit], health: HealthConfig, now: datetime
) -> list[Breach]:
    row = health.thresholds.unit_failure_rate
    since = now - timedelta(days=_WEEK_DAYS)
    started = [u for u in units if (at := u.started_at) is not None and since <= at <= now]
    failed = [u for u in started if any(e.get("state") == UnitState.FAILED for e in u.history)]
    if not started or len(failed) / len(started) <= row.limit:
        return []
    evidence = [f"{len(failed)} failed of {len(started)} started"]
    for unit in failed:
        entry = next(e for e in unit.history if e.get("state") == UnitState.FAILED)
        lines = str(entry.get("note") or "").splitlines()
        evidence.append(
            f"{unit.id}: {entry.get('cause') or 'no cause'}: {lines[0] if lines else ''}"
        )
    return [
        Breach(
            signal="unit_failure_rate",
            observed=len(failed) / len(started),
            limit=row.limit,
            correction=row.correction,
            evidence=tuple(evidence),
        )
    ]
