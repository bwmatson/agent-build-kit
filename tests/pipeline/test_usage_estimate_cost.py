"""On the cost basis the estimate adds recorded cost times the window's points per dollar, over
every row of the account with a unit or without one, and the flat allowance only where cost is
unknown (spec: usage-pause).

Only the endpoint and the home directory are faked (`tests/usage_host.py`); the kept reading,
the ledger and the kept calibration are the real files beside the cache."""

from datetime import timedelta

from agent_build_kit.pipeline.usage_guard import decide_start
from tests.usage_cost_estimate import (
    HOUR,
    MINUTE,
    admit,
    cost_fit,
    keep_fits,
    paused,
    reading_at,
    row,
)
from tests.usage_host import Host


def test_the_observed_case_is_estimated_from_its_cost_and_allowed(host: Host) -> None:
    paused(host, session=61.0)
    keep_fits(host, session=cost_fit(2.65, intercept=5, flat=17))
    row(host, "review", 0.97, unit="feature/1")
    row(host, "rework", 0.48, unit="feature/2")

    decision = decide_start(unit="feature/3")

    assert decision.may_start
    assert host.asked == 0
    assert "session ~69% estimated (61% read + 8% spent from $1.45 recorded) under 80%" in (
        decision.reason
    )


def test_a_unit_with_three_review_rounds_costs_more_than_one_with_one(host: Host) -> None:
    paused(host, session=70.0)
    keep_fits(host, session=cost_fit(2.65))
    row(host, "review", 0.97, unit="feature/1", round=1)
    row(host, "review", 0.50, unit="feature/1", round=2, ago=9 * MINUTE)
    row(host, "review", 0.39, unit="feature/1", round=3, ago=8 * MINUTE)

    three = decide_start().reason

    assert "session ~75% estimated (70% read + 5% spent from $1.86 recorded)" in three


def test_a_unit_with_one_review_round_adds_less(host: Host) -> None:
    paused(host, session=70.0)
    keep_fits(host, session=cost_fit(2.65))
    row(host, "review", 0.97, unit="feature/1", round=1)

    assert "session ~73% estimated (70% read + 3% spent from $0.97 recorded)" in (
        decide_start().reason
    )


def test_a_row_with_no_unit_is_counted_by_its_cost(host: Host) -> None:
    paused(host, session=60.0)
    keep_fits(host, session=cost_fit(2.65))
    row(host, "plan", 2.10)

    assert "session ~66% estimated (60% read + 6% spent from $2.10 recorded)" in (
        decide_start().reason
    )


def test_a_row_with_no_cost_adds_nothing_and_counts_no_unit(host: Host) -> None:
    paused(host, session=60.0)
    keep_fits(host, session=cost_fit(2.65))
    row(host, "login_refresh", None)
    row(host, "plan", 1.00)

    reason = decide_start().reason

    assert "session ~63% estimated (60% read + 3% spent from $1.00 recorded)" in reason
    assert "not yet recorded" not in reason


def test_a_row_before_the_reading_adds_nothing_and_one_at_its_time_does(host: Host) -> None:
    paused(host, session=60.0)
    keep_fits(host, session=cost_fit(2.65))
    row(host, "plan", 3.00, at=reading_at(host) - MINUTE)
    row(host, "plan", 1.00, at=reading_at(host))

    assert "session ~63% estimated (60% read + 3% spent from $1.00 recorded)" in (
        decide_start().reason
    )


def test_a_row_of_another_account_adds_nothing(host: Host) -> None:
    paused(host, session=60.0)
    keep_fits(host, session=cost_fit(2.65))
    row(host, "plan", 2.00, account="/elsewhere")
    row(host, "plan", 1.00)

    assert "session ~63% estimated (60% read + 3% spent from $1.00 recorded)" in (
        decide_start().reason
    )


# --- where cost is unknown the flat allowance stands in -----------------------------------------


def test_an_admitted_unit_with_no_row_counts_the_flat_allowance(host: Host) -> None:
    paused(host, session=50.0)
    keep_fits(host, session=cost_fit(2.65, flat=10))
    admit(host, "feature/1")

    reason = decide_start().reason

    assert "session ~60% estimated (50% read + 10% spent" in reason
    assert "1 unit not yet recorded" in reason


def test_a_row_with_a_cost_replaces_the_flat_allowance_and_does_not_add_to_it(host: Host) -> None:
    paused(host, session=50.0)
    keep_fits(host, session=cost_fit(2.65, flat=10))
    admit(host, "feature/1")
    row(host, "implement", 0.50, unit="feature/1", ago=5 * MINUTE)

    reason = decide_start().reason

    assert "session ~51% estimated (50% read + 1% spent from $0.50 recorded)" in reason
    assert "not yet recorded" not in reason


def test_a_unit_with_two_rows_and_no_cost_counts_the_flat_allowance_once(host: Host) -> None:
    paused(host, session=50.0)
    keep_fits(host, session=cost_fit(2.65, flat=10))
    row(host, "implement", None, unit="feature/1", ago=8 * MINUTE)
    row(host, "tests", None, unit="feature/1", ago=5 * MINUTE)

    reason = decide_start().reason

    assert "session ~60% estimated (50% read + 10% spent" in reason
    assert "1 unit not yet recorded" in reason


def test_a_unit_with_some_cost_counts_its_cost_only(host: Host) -> None:
    paused(host, session=50.0)
    keep_fits(host, session=cost_fit(2.65, flat=10))
    row(host, "implement", 0.50, unit="feature/1", ago=8 * MINUTE)
    row(host, "tests", None, unit="feature/1", ago=5 * MINUTE)

    reason = decide_start().reason

    assert "session ~51% estimated (50% read + 1% spent from $0.50 recorded)" in reason
    assert "not yet recorded" not in reason


def test_the_intercept_adds_its_points_for_each_hour_since_the_reading(host: Host) -> None:
    paused(host, session=50.0, age=2 * HOUR + timedelta(seconds=30))
    keep_fits(host, session=cost_fit(2.65, intercept=5))

    assert "session ~60% estimated (50% read + 10% spent" in decide_start().reason
