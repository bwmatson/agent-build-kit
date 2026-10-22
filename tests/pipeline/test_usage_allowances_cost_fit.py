"""The cost fit: the non-negative line of points gained on recorded cost, and on hours where
the window's intercept is on, scaled by a residual quantile and rounded up (spec: usage-pause)."""

from collections.abc import Callable
from datetime import UTC, datetime

import pytest

from agent_build_kit.config import ClaudeLimitsConfig, UsageWindowConfig
from agent_build_kit.pipeline.usage_allowances import Calibrated, Window, calibrated_allowances
from tests.usage_cost_records import Gap, cost_gaps, varied

NOW = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
NO_INTERCEPT = ClaudeLimitsConfig(session=UsageWindowConfig(usage_estimate_intercept=False))


def calibrate(
    window: Window, gaps: list[Gap], limits: ClaudeLimitsConfig | None = None
) -> Calibrated:
    calls, ledger = cost_gaps(window, gaps)
    return calibrated_allowances(calls, ledger, limits=limits or ClaudeLimitsConfig(), now=NOW)[
        window
    ]


def gain_is(per_dollar: float, per_hour: float = 0.0) -> Callable[[float, float, int], float]:
    return lambda cost, hours, _: per_dollar * cost + per_hour * hours


def test_twenty_pairs_of_exactly_three_points_a_dollar_give_three_and_no_scale() -> None:
    kept = calibrate("session", varied(20, gain_is(3)))

    assert kept.points_per_usd == pytest.approx(3.00, abs=1e-9)
    assert kept.intercept_per_hour == pytest.approx(0.00, abs=1e-9)
    assert kept.safety_scale == pytest.approx(1.0, abs=1e-9)


def test_an_intercept_is_the_points_an_hour_that_are_not_recorded() -> None:
    gaps = varied(20, gain_is(2, 4))

    on = calibrate("session", gaps)
    off = calibrate("session", gaps, NO_INTERCEPT)

    assert on.points_per_usd == pytest.approx(2.00, abs=1e-9)
    assert on.intercept_per_hour == pytest.approx(4.00, abs=1e-9)
    assert off.intercept_per_hour == 0.0
    assert off.points_per_usd is not None and off.points_per_usd > 2.00


def test_an_intercept_that_would_be_negative_is_refit_through_the_origin() -> None:
    gaps = varied(24, gain_is(3, -1), costs=(2.0, 3.0, 4.0, 5.0), hours=(1.0, 2.0, 3.0))

    on = calibrate("session", gaps)
    off = calibrate("session", gaps, NO_INTERCEPT)

    assert on.intercept_per_hour == 0.0
    assert on.points_per_usd == off.points_per_usd


def test_a_fit_that_would_not_be_above_zero_is_no_fit() -> None:
    kept = calibrate("session", varied(12, gain_is(0)))

    assert kept.points_per_usd is None and kept.intercept_per_hour is None
    assert (kept.basis, kept.reason) == ("units", "no_fit")


def test_with_scatter_the_scale_keeps_nine_gaps_in_ten_under_the_kept_prediction() -> None:
    scatter = (-2, -1, 0, 1, 2, 3, -3, 2, 0, -1)
    gaps = varied(
        30,
        lambda cost, hours, index: 3 * cost + scatter[index % len(scatter)],
        costs=(2.0, 3.0, 4.0, 5.0),
        hours=(1.0, 2.0, 3.0),
    )

    kept = calibrate("session", gaps)

    assert kept.points_per_usd is not None and kept.intercept_per_hour is not None
    assert kept.safety_scale is not None and 1 < kept.safety_scale <= 2
    under = sum(
        gap.gain <= kept.points_per_usd * (gap.cost or 0) + kept.intercept_per_hour * gap.hours
        for gap in gaps
    )
    assert under >= 27


def test_the_kept_figures_are_rounded_up_to_a_hundredth() -> None:
    # One point for three dollars each time is exactly a third of a point a dollar.
    kept = calibrate("weekly", [Gap(gain=1, cost=3.0) for _ in range(10)])

    assert kept.points_per_usd == pytest.approx(0.34, abs=1e-9)
    assert kept.safety_scale == pytest.approx(1.0, abs=1e-9)


def test_fewer_pairs_than_the_minimum_make_no_fit_and_say_how_many_are_held() -> None:
    kept = calibrate("session", varied(7, gain_is(3)))

    assert kept.points_per_usd is None
    assert (kept.basis, kept.reason, kept.cost_pairs_held) == ("units", "too_few_pairs", 7)


def test_only_the_newest_pairs_of_the_window_are_fitted() -> None:
    older = varied(10, gain_is(9))
    newest = varied(30, gain_is(3))

    kept = calibrate("session", older + newest)

    assert kept.points_per_usd == pytest.approx(3.00, abs=1e-9)


def test_the_weekly_fit_over_whole_point_gains_is_one_figure_through_the_origin() -> None:
    costs = (0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0)
    gaps = varied(100, lambda cost, hours, index: int(cost / 2), costs=costs)
    assert {gap.gain for gap in gaps} == {0, 1, 2}

    kept = calibrate("weekly", gaps)

    assert kept.points_per_usd is not None and kept.points_per_usd > 0
    assert kept.intercept_per_hour == 0.0
