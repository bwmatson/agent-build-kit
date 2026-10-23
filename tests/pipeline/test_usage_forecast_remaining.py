"""A later gate asks for its step and a unit past some rounds has the rest still to come,
conditional on its having got there (spec: usage-pause)."""

import pytest

from agent_build_kit.pipeline.usage_forecast_unit import (
    UnitForecast,
    forecast_remaining,
    forecast_step,
)
from agent_build_kit.pipeline.verdict import ReviewTier
from tests.usage_forecast_fixtures import spec_history

FULL = ReviewTier.FULL


def step(round: int) -> UnitForecast:
    history = spec_history()
    return forecast_step(
        history.records,
        history.verdicts,
        tier=FULL,
        estimated_lines=10,
        node="review",
        round=round,
        points_per_usd=2.5,
        flat_allowance=11,
        min_runs=10,
        quantile=0.5,
    )


def remaining(rounds_run: int) -> UnitForecast:
    history = spec_history()
    return forecast_remaining(
        history.records,
        history.verdicts,
        tier=FULL,
        estimated_lines=10,
        node="review",
        rounds_run=rounds_run,
        points_per_usd=2.5,
        flat_allowance=11,
        min_runs=10,
        quantile=0.5,
    )


def test_a_unit_at_its_third_review_round_asks_for_that_step_at_its_mean() -> None:
    found = step(3)

    assert found.usd == pytest.approx(0.40)
    assert found.points == pytest.approx(1.0)


def test_nothing_is_still_to_come_after_the_last_round() -> None:
    found = remaining(3)

    assert found.usd == 0
    assert found.points == 0


def test_a_unit_past_two_rounds_has_the_conditional_third_still_to_come() -> None:
    assert remaining(2).usd == pytest.approx(0.40 * 6 / 18)


def test_a_unit_past_one_round_has_each_later_round_given_it_got_there() -> None:
    # Round 2 at 0.9 and round 3 at 0.3 of the first round's units.
    assert remaining(1).usd == pytest.approx(0.9 * 0.5 + 0.3 * 0.4)


def test_a_later_gate_is_the_cell_at_its_mean_and_not_its_chance_weighted_cost() -> None:
    assert step(2).usd == pytest.approx(0.50)
    assert step(2).usd != pytest.approx(0.45)
