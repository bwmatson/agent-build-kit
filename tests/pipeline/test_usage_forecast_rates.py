"""The chance of reaching a cell is an upper bound at a high quantile of the observed share,
and never rises with the round (spec: usage-pause)."""

import pytest

from agent_build_kit.pipeline.usage_forecast_history import reach_rate, tier_cells
from agent_build_kit.pipeline.verdict import ReviewTier
from tests.usage_forecast_fixtures import Fixture, call, chance


def test_a_thin_history_is_read_cautiously() -> None:
    assert 0.3 < reach_rate(3, 10, 0.9) <= 1


def test_more_units_narrow_the_margin() -> None:
    assert 0.3 < reach_rate(60, 200, 0.9) < reach_rate(3, 10, 0.9)


def test_a_quantile_of_one_half_is_the_observed_share() -> None:
    assert reach_rate(6, 20, 0.5) == pytest.approx(0.3)


def test_no_unit_reaching_it_still_has_a_bound() -> None:
    assert reach_rate(0, 10, 0.9) > 0


def test_the_bound_is_at_most_one() -> None:
    assert reach_rate(10, 10, 0.9) == 1


def test_the_chances_of_a_steps_rounds_do_not_rise() -> None:
    fixture = Fixture()
    fixture.units(10, ReviewTier.AUTO, [("review", 1, 1.0)])
    # Two units ran a round 2 and three a round 3, so the observed share rises.
    for unit in ("u0/1", "u1/1"):
        fixture.records.append(call(unit, "review", 2, 0.5))
    for unit in ("u0/1", "u1/1", "u2/1"):
        fixture.records.append(call(unit, "review", 3, 0.4))

    for quantile in (0.5, 0.9):
        found = tier_cells(
            fixture.records,
            fixture.verdicts,
            tier=ReviewTier.AUTO,
            estimated_lines=10,
            points_per_usd=2.5,
            min_runs=10,
            quantile=quantile,
        )
        assert chance(found, "review", 3) <= chance(found, "review", 2)


def test_a_steps_total_chance_over_its_models_does_not_rise_with_the_round() -> None:
    fixture = Fixture()
    for n in range(20):
        unit = fixture.unit(f"u{n}", ReviewTier.AUTO, [])
        early = "model-a" if n < 10 else "model-b"
        fixture.records.append(call(unit, "review", 1, 1.0, model=early))
        if n < 15:
            fixture.records.append(call(unit, "review", 2, 0.5, model="model-b"))

    found = tier_cells(
        fixture.records,
        fixture.verdicts,
        tier=ReviewTier.AUTO,
        estimated_lines=10,
        points_per_usd=2.5,
        min_runs=10,
        quantile=0.5,
    )

    totals = {
        round: sum(c.chance for c in found.cells if c.cell.round == round) for round in (1, 2)
    }
    assert totals[1] == pytest.approx(1.0)
    assert totals[2] == pytest.approx(0.75)
