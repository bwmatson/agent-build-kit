"""A later gate asks for its step and a unit past some rounds has the rest still to come,
conditional on its having got there (spec: usage-pause)."""

import pytest

from agent_build_kit.pipeline.usage_forecast_unit import (
    UnitForecast,
    forecast_remaining,
    forecast_step,
)
from agent_build_kit.pipeline.verdict import ReviewTier
from tests.usage_forecast_fixtures import Fixture, call, spec_history

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
        min_runs=5,
        quantile=0.5,
    )


def remaining(last_round: int) -> UnitForecast:
    history = spec_history()
    return forecast_remaining(
        history.records,
        history.verdicts,
        tier=FULL,
        estimated_lines=10,
        node="review",
        last_round=last_round,
        points_per_usd=2.5,
        flat_allowance=11,
        min_runs=5,
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


def ask(history: Fixture, node: str, round: int) -> UnitForecast:
    return forecast_step(
        history.records,
        history.verdicts,
        tier=FULL,
        estimated_lines=10,
        node=node,
        round=round,
        points_per_usd=2.5,
        flat_allowance=11,
        min_runs=5,
        quantile=0.5,
    )


def test_a_step_run_under_two_models_is_forecast_once_at_the_mean_over_both() -> None:
    history = Fixture()
    history.units(20, FULL, [("review", 1, 1.0)])
    for n in range(10):
        history.records.append(call(f"u{n}/1", "review", 2, 0.5, model="model-a"))
    for n in range(10, 20):
        history.records.append(call(f"u{n}/1", "review", 2, 0.5, model="model-b"))

    assert ask(history, "review", 2).usd == pytest.approx(0.50)


def test_a_step_numbered_from_zero_conditions_on_its_last_round() -> None:
    history = Fixture()
    history.units(20, FULL, [("review", 1, 1.0)])
    for n in range(10):
        history.records.append(call(f"u{n}/1", "rework", 0, 0.5))
    for n in range(5):
        history.records.append(call(f"u{n}/1", "rework", 1, 0.3))

    found = forecast_remaining(
        history.records,
        history.verdicts,
        tier=FULL,
        estimated_lines=10,
        node="rework",
        last_round=0,
        points_per_usd=2.5,
        flat_allowance=11,
        min_runs=5,
        quantile=0.5,
    )

    # Round 1 was reached by 5 of 20 and round 0 by 10 of 20.
    assert found.usd == pytest.approx(0.5 * 0.3)


def test_a_round_the_tier_never_ran_of_a_node_it_did_is_the_mean_of_the_node() -> None:
    history = Fixture()
    history.units(20, FULL, [("review", 1, 1.0), ("rework", 0, 0.5)])

    found = ask(history, "rework", 1)

    assert not found.prior
    assert found.usd == pytest.approx(0.5)
