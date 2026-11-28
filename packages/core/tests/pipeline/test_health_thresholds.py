"""The health thresholds (spec: health-thresholds): pure inputs in, each breach with its
signal, observed value, limit, correction and evidence out."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import pytest

from agent_build_kit.config import HealthConfig, HealthThresholds, ThresholdRow
from agent_build_kit.pipeline.health_thresholds import Breach, evaluate_thresholds
from agent_build_kit.pipeline.trusted_cost import JudgedChange, TrustedChanges, Verdict, Window
from agent_build_kit.pipeline.unit_store import StoredUnit
from agent_build_kit.pipeline.usage_report import DaySpend
from tests.factories import stored_unit

NOW = datetime(2026, 11, 27, 12, tzinfo=UTC)
NO_WINDOW = Window(costed=0, uncosted=0, cost=0.0, cost_per_trusted_change=None)
NO_CHANGES = TrustedChanges(
    changes=(),
    latest=NO_WINDOW,
    previous=NO_WINDOW,
    pending_count=0,
    pending_cost=0.0,
    unchecked=(),
)


def ago(days: float) -> datetime:
    return NOW - timedelta(days=days)


def spend(days_ago: int, plan: float, total: float) -> DaySpend:
    return DaySpend(
        day=ago(days_ago).date().isoformat(),
        by_role={"plan": plan, "implement": total - plan},
        total=total,
    )


def only(
    signal: str,
    *,
    days: Sequence[DaySpend] = (),
    trusted: TrustedChanges = NO_CHANGES,
    units: Sequence[StoredUnit] = (),
    health: HealthConfig | None = None,
) -> list[Breach]:
    """The breaches of one signal, from `evaluate_thresholds` on the given inputs."""
    report = evaluate_thresholds(days, trusted, units, health or HealthConfig(), now=NOW)
    return [b for b in report.breaches if b.signal == signal]


def trusted_with(latest_costs: list[float], previous_cost: float | None) -> TrustedChanges:
    """Trusted changes of the latest window (merged 40 days ago) at the given costs, one of 100
    USD in the previous window (merged 70 days ago), and the windows' figures."""
    changes = [
        JudgedChange(change=f"c{n}", merged_at=ago(40), verdict=Verdict.TRUSTED, cost=cost)
        for n, cost in enumerate(latest_costs)
    ]
    changes.append(
        JudgedChange(change="old", merged_at=ago(70), verdict=Verdict.TRUSTED, cost=100.0)
    )
    latest = Window(
        costed=len(latest_costs),
        uncosted=0,
        cost=sum(latest_costs),
        cost_per_trusted_change=sum(latest_costs) / len(latest_costs),
    )
    previous = (
        NO_WINDOW
        if previous_cost is None
        else Window(costed=1, uncosted=0, cost=previous_cost, cost_per_trusted_change=previous_cost)
    )
    return TrustedChanges(
        changes=tuple(changes),
        latest=latest,
        previous=previous,
        pending_count=0,
        pending_cost=0.0,
        unchecked=(),
    )


def failing_unit(n: int, *, began_days_ago: float, failed: bool, note: str = "") -> StoredUnit:
    history: list[dict] = [{"state": "running", "at": ago(began_days_ago).isoformat()}]
    if failed:
        history.append(
            {
                "state": "failed",
                "at": ago(began_days_ago - 0.1).isoformat(),
                "cause": f"cause-{n}",
                "note": note,
            }
        )
    return stored_unit(f"change-{n}/1", change=f"change-{n}", history=tuple(history))


def week_of_units(failed: int) -> list[StoredUnit]:
    """Eight units that began in the last 7 days, `failed` of them failed, and one that began
    8 days ago and failed."""
    units = [
        failing_unit(
            n, began_days_ago=1 + n * 0.5, failed=n < failed, note=f"broke {n}\nsecond line {n}"
        )
        for n in range(8)
    ]
    return [*units, failing_unit(9, began_days_ago=8, failed=True, note="too old")]


def test_a_day_dominated_by_plan_reviews_breaches_with_its_figures_and_correction() -> None:
    health = HealthConfig()
    days = (spend(3, 10.0, 40.0), spend(2, 30.0, 40.0))

    (breach,) = only("plan_review_share", days=days, health=health)

    row = health.thresholds.plan_review_share
    assert breach.observed == pytest.approx(0.75)
    assert breach.limit == row.limit
    assert breach.correction == row.correction
    evidence = "\n".join(breach.evidence)
    assert ago(2).date().isoformat() in evidence
    assert "30.00" in evidence
    assert "40.00" in evidence
    assert ago(3).date().isoformat() not in evidence


def test_a_day_older_than_seven_days_is_not_evaluated() -> None:
    assert only("plan_review_share", days=(spend(9, 90.0, 100.0),)) == []


@pytest.mark.parametrize(("latest_odd", "total_cost", "breaches"), [(5.2, 88.2, 1), (4.5, 87.5, 0)])
def test_a_rise_in_the_cost_per_trusted_change_breaches_above_the_limit_only(
    latest_odd: float, total_cost: float, breaches: int
) -> None:
    costs = [20.0, 18.0, 16.0, 14.0, 12.0, latest_odd, 3.0]
    assert sum(costs) == pytest.approx(total_cost)

    found = only("cost_per_trusted_change", trusted=trusted_with(costs, 10.0))

    assert len(found) == breaches


@pytest.mark.parametrize(("top", "named"), [(3, ["c0", "c1", "c2"]), (2, ["c0", "c1"])])
def test_the_cost_breach_names_the_most_expensive_changes_of_the_latest_window(
    top: int, named: list[str]
) -> None:
    health = HealthConfig(top=top)
    costs = [20.0, 18.0, 16.0, 14.0, 12.0, 5.2, 3.0]

    (breach,) = only("cost_per_trusted_change", trusted=trusted_with(costs, 10.0), health=health)

    row = health.thresholds.cost_per_trusted_change
    assert breach.observed == pytest.approx(0.26)
    assert breach.limit == row.limit
    assert breach.correction == row.correction
    assert len(breach.evidence) == top
    evidence = "\n".join(breach.evidence)
    for change in named:
        assert change in evidence
    for other in ("c3", "c4", "c5", "c6", "old"):
        assert other not in evidence


def test_a_window_without_a_costed_trusted_change_cannot_breach_and_is_named() -> None:
    report = evaluate_thresholds(
        (),
        trusted_with([20.0, 18.0], None),
        (),
        HealthConfig(),
        now=NOW,
    )

    assert [b for b in report.breaches if b.signal == "cost_per_trusted_change"] == []
    assert report.lacking == ("previous",)


def test_a_week_of_failures_breaches_with_the_failed_units_their_causes_and_first_notes() -> None:
    health = HealthConfig()

    (breach,) = only("unit_failure_rate", units=week_of_units(3), health=health)

    row = health.thresholds.unit_failure_rate
    assert breach.observed == pytest.approx(3 / 8)
    assert breach.limit == row.limit
    assert breach.correction == row.correction
    evidence = "\n".join(breach.evidence)
    for n in range(3):
        assert f"change-{n}/1" in evidence
        assert f"cause-{n}" in evidence
        assert f"broke {n}" in evidence
        assert f"second line {n}" not in evidence
    assert "change-9/1" not in evidence
    assert "too old" not in evidence


def test_two_failed_units_over_eight_started_do_not_breach() -> None:
    assert only("unit_failure_rate", units=week_of_units(2)) == []


def test_no_unit_started_in_the_week_is_no_breach() -> None:
    old = [failing_unit(1, began_days_ago=8, failed=True)]

    assert only("unit_failure_rate", units=old) == []


def test_a_configured_limit_and_correction_are_the_ones_carried() -> None:
    health = HealthConfig(
        thresholds=HealthThresholds(
            unit_failure_rate=ThresholdRow(limit=0.1, correction="read the log")
        )
    )

    (breach,) = only("unit_failure_rate", units=week_of_units(1), health=health)

    assert breach.limit == 0.1
    assert breach.correction == "read the log"
