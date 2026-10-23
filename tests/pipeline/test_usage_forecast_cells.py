"""A cell's chance is the share of the tier's units that ran it and its cost the mean of its
calls, with the stated fallbacks and the prior (spec: usage-pause)."""

import pytest

from agent_build_kit.pipeline.usage_forecast_history import TierCells, tier_cells
from agent_build_kit.pipeline.verdict import ReviewTier
from tests.usage_forecast_fixtures import Fixture, call, chance, cost

AUTO = ReviewTier.AUTO
FULL = ReviewTier.FULL


def cells(
    fixture: Fixture,
    tier: ReviewTier | None = AUTO,
    *,
    estimated_lines: int = 10,
    points_per_usd: float | None = 2.5,
) -> TierCells:
    return tier_cells(
        fixture.records,
        fixture.verdicts,
        tier=tier,
        estimated_lines=estimated_lines,
        points_per_usd=points_per_usd,
        min_runs=10,
        quantile=0.5,
    )


def test_a_cells_chance_is_the_share_of_units_that_ran_it_and_its_cost_the_mean() -> None:
    fixture = Fixture()
    fixture.units(10, AUTO, [("review", 1, 1.0)])
    # Six units ran a round 2, each twice: twelve calls, enough for the cell's own mean.
    for n in range(6):
        fixture.records.append(call(f"u{n}/1", "review", 2, 0.25))
        fixture.records.append(call(f"u{n}/1", "review", 2, 0.5))

    found = cells(fixture)

    assert not found.prior
    assert found.units == 10
    assert chance(found, "review", 1) == 1.0
    assert chance(found, "review", 2) == pytest.approx(0.6)
    assert cost(found, "review", 1) == pytest.approx(1.0)
    assert cost(found, "review", 2) == pytest.approx(0.375)


def test_a_cell_under_the_minimum_calls_takes_the_mean_over_every_model() -> None:
    fixture = Fixture()
    fixture.units(10, AUTO, [("implement", 0, 0.5)])
    for n in range(4):
        fixture.records.append(call(f"u{n}/1", "review", 3, 0.4, model="model-b"))
    for n in range(4, 10):
        fixture.records.append(call(f"u{n}/1", "review", 3, 1.0, model="model-a"))

    found = cells(fixture)

    by_model = {
        c.cell.model: c for c in found.cells if c.cell.node == "review" and c.cell.round == 3
    }
    assert by_model["model-b"].cost_usd == pytest.approx(0.76)
    assert by_model["model-a"].cost_usd == pytest.approx(0.76)
    assert by_model["model-b"].chance == pytest.approx(0.4)


def test_a_step_with_fewer_calls_than_the_minimum_takes_the_mean_of_its_node() -> None:
    fixture = Fixture()
    fixture.units(10, AUTO, [("review", 1, 2.0)])
    fixture.records.append(call("u0/1", "review", 2, 0.5, model="model-b"))
    fixture.records.append(call("u1/1", "review", 2, 0.7, model="model-b"))

    found = cells(fixture)

    # Twelve calls of the node: ten at 2.0 and two at 0.5 and 0.7.
    assert cost(found, "review", 2) == pytest.approx((20 + 1.2) / 12)


def test_a_tier_under_the_minimum_units_is_the_prior() -> None:
    fixture = Fixture()
    fixture.units(9, FULL, [("review", 1, 1.0)])
    fixture.units(10, AUTO, [("review", 1, 1.0)])

    thin = cells(fixture, FULL)
    enough = cells(fixture, AUTO)

    assert thin.prior
    assert thin.cells == ()
    assert not enough.prior


def test_a_window_on_the_units_basis_is_the_prior() -> None:
    fixture = Fixture()
    fixture.units(10, AUTO, [("review", 1, 1.0)])

    found = cells(fixture, points_per_usd=None)

    assert found.prior
    assert found.cells == ()


def test_a_unit_with_no_stored_tier_is_the_prior() -> None:
    fixture = Fixture()
    fixture.units(10, AUTO, [("review", 1, 1.0)])

    assert cells(fixture, None).prior


def test_a_cell_the_tier_never_ran_is_not_there() -> None:
    fixture = Fixture()
    fixture.units(10, AUTO, [("review", 1, 1.0)])
    fixture.units(10, FULL, [("review", 1, 1.0), ("rework", 0, 0.5)])

    assert [c.cell.node for c in cells(fixture, AUTO).cells] == ["review"]


def sized(small: int, large: int) -> Fixture:
    """A tier of `small` units of 10 changed lines, none with a review round 2, and `large` of
    100, each with one."""
    fixture = Fixture()
    fixture.units(small, AUTO, [("review", 1, 1.0)], lines=10)
    fixture.units(large, AUTO, [("review", 1, 1.0), ("review", 2, 0.5)], lines=100)
    return fixture


def test_size_splits_the_tier_when_each_band_has_the_minimum() -> None:
    fixture = sized(10, 10)

    large = cells(fixture, estimated_lines=100)
    small = cells(fixture, estimated_lines=10)

    assert chance(large, "review", 2) == 1.0
    assert chance(small, "review", 2) == 0.0
    assert (large.band, small.band) == ("large", "small")


def test_size_is_not_used_when_a_band_is_thin() -> None:
    fixture = sized(11, 9)

    found = cells(fixture, estimated_lines=100)

    assert found.band == "all"
    assert chance(found, "review", 2) == pytest.approx(9 / 20)
