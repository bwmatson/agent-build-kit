"""The cost fit is adopted for a window only when, judged walk-forward over its newest cost pairs,
it has no more false allows than the flat figure (spec: usage-pause).

Every gap starts at 60 against a threshold of 70 and a margin of 5, so an estimate lets a start
through when it adds less than 5 points, and it is a false allow when the gap then gained 10 or
more. A gap of 3 points a dollar is estimated exactly by the cost fit; a gap with no unit is
estimated by nothing by the flat figure."""

from datetime import UTC, datetime

import pytest

from agent_build_kit.config import ClaudeLimitsConfig, UsageWindowConfig
from agent_build_kit.pipeline.usage_allowances import Calibrated, calibrated_allowances
from tests.usage_cost_records import Gap, cost_gaps

NOW = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
LIMITS = ClaudeLimitsConfig(session=UsageWindowConfig(usage_estimate_intercept=False))
COSTS = (2.0, 3.0, 4.0)
HOURS = (1.0, 1.5, 2.0, 2.5)


def steady(index: int) -> Gap:
    """A gap of one unit that gained exactly 3 points for each dollar."""
    cost = COSTS[index % len(COSTS)]
    return Gap(before=60, gain=round(3 * cost), cost=cost, hours=HOURS[index % len(HOURS)])


def run(count: int, odd: dict[int, Gap]) -> list[Gap]:
    """`count` steady gaps, those at the indices of `odd` replaced."""
    return [odd.get(index, steady(index)) for index in range(count)]


# Gained 12 for 4 dollars, which the cost fit estimates and nothing counts a unit for.
NO_UNIT = Gap(before=60, gain=12, cost=4.0, units=0)
# Gained 10 for half a dollar: the cost fit expects 1.5.
SURPRISE = Gap(before=60, gain=10, cost=0.5)


def calibrate(gaps: list[Gap], limits: ClaudeLimitsConfig = LIMITS) -> Calibrated:
    calls, ledger = cost_gaps("session", gaps)
    return calibrated_allowances(calls, ledger, limits=limits, now=NOW)["session"]


def test_one_false_allow_for_cost_against_three_for_flat_adopts_the_cost_fit() -> None:
    gaps = run(20, {9: NO_UNIT, 12: NO_UNIT, 15: NO_UNIT, 19: SURPRISE})

    kept = calibrate(gaps)

    assert kept.basis == "cost"
    assert (kept.false_allows_cost, kept.false_allows_flat) == (1, 3)
    assert kept.cost_pairs_judged == 12


def test_three_false_allows_for_cost_against_one_for_flat_does_not_adopt() -> None:
    gaps = run(20, {10: NO_UNIT, 17: SURPRISE, 18: SURPRISE, 19: SURPRISE})

    kept = calibrate(gaps)

    assert (kept.basis, kept.reason) == ("units", "more_false_allows")
    assert (kept.false_allows_cost, kept.false_allows_flat) == (3, 1)
    assert kept.points_per_usd is not None


def test_twelve_pairs_judge_four_gaps_and_do_not_adopt() -> None:
    kept = calibrate(run(12, {}))

    assert (kept.basis, kept.reason) == ("units", "too_few_judged")
    assert (kept.cost_pairs_held, kept.cost_pairs_judged) == (12, 4)
    assert kept.points_per_usd is not None


def test_twenty_pairs_judge_twelve() -> None:
    kept = calibrate(run(20, {}))

    assert kept.cost_pairs_judged == 12
    assert kept.basis == "cost"


def test_the_threshold_is_the_windows_own_pause_percent() -> None:
    gaps = run(20, {10: NO_UNIT, 17: SURPRISE, 18: SURPRISE, 19: SURPRISE})
    higher = ClaudeLimitsConfig(
        session=UsageWindowConfig(usage_pause_pct=80, usage_estimate_intercept=False)
    )

    kept = calibrate(gaps, higher)

    assert (kept.false_allows_cost, kept.false_allows_flat) == (0, 0)
    assert kept.basis == "cost"


def test_the_margin_is_the_headroom_margin_setting() -> None:
    gaps = run(20, {10: NO_UNIT, 17: SURPRISE, 18: SURPRISE, 19: SURPRISE})
    wider = ClaudeLimitsConfig(
        session=UsageWindowConfig(usage_estimate_intercept=False), usage_headroom_margin_pct=15
    )

    kept = calibrate(gaps, wider)

    assert (kept.false_allows_cost, kept.false_allows_flat) == (0, 0)


def test_the_basis_units_fits_nothing_and_keeps_the_flat_figure() -> None:
    gaps = run(20, {})
    limits = ClaudeLimitsConfig(
        session=UsageWindowConfig(usage_estimate_basis="units", usage_estimate_intercept=False)
    )

    kept = calibrate(gaps, limits)

    assert (kept.basis, kept.reason) == ("units", "basis_units")
    assert kept.points_per_usd is None and kept.safety_scale is None
    assert kept.quantile_pct_per_unit is not None and kept.pairs_available == 20


def test_a_window_is_judged_apart_from_the_other() -> None:
    calls, ledger = cost_gaps("session", run(20, {}))
    # The same rows, with a week that gained nothing in any of them: nothing to fit.
    still, _ = cost_gaps("weekly", [steady(i).model_copy(update={"gain": 0}) for i in range(20)])

    found = calibrated_allowances([*calls, *still], ledger, limits=LIMITS, now=NOW)

    assert found["session"].basis == "cost"
    assert (found["weekly"].basis, found["weekly"].reason) == ("units", "no_fit")


def test_a_kept_cost_fit_carries_its_figures() -> None:
    kept = calibrate(run(20, {}))

    assert kept.points_per_usd == pytest.approx(3.00, abs=1e-9)
    assert kept.safety_scale == pytest.approx(1.0, abs=1e-9)
    assert kept.cost_pairs_held == 20
