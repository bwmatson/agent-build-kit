"""A tier, window or unit with too little to go on is forecast at the window's flat per-unit
allowance, with the prior flagged (spec: usage-pause)."""

from agent_build_kit.pipeline.usage_forecast_unit import UnitForecast, forecast_unit
from agent_build_kit.pipeline.verdict import ReviewTier
from tests.usage_forecast_fixtures import Fixture, spec_history

FLAT = 11


def forecast(
    history: Fixture, tier: ReviewTier | None, points_per_usd: float | None = 2.5
) -> UnitForecast:
    return forecast_unit(
        history.records,
        history.verdicts,
        tier=tier,
        estimated_lines=10,
        points_per_usd=points_per_usd,
        flat_allowance=FLAT,
        min_runs=10,
        quantile=0.5,
    )


def nine_full_and_twenty_auto() -> Fixture:
    history = spec_history()
    for unit in [u for u in history.verdicts if u.startswith("f")][9:]:
        del history.verdicts[unit]
    return history


def test_a_tier_with_nine_units_is_forecast_at_the_flat_allowance() -> None:
    found = forecast(nine_full_and_twenty_auto(), ReviewTier.FULL)

    assert found.prior
    assert found.points == FLAT


def test_a_window_on_the_units_basis_is_forecast_at_the_flat_allowance() -> None:
    found = forecast(spec_history(), ReviewTier.AUTO, points_per_usd=None)

    assert found.prior
    assert found.points == FLAT


def test_a_unit_with_no_stored_tier_is_forecast_at_the_flat_allowance() -> None:
    found = forecast(spec_history(), None)

    assert found.prior
    assert found.points == FLAT


def test_a_tier_with_enough_units_beside_them_is_not_the_prior() -> None:
    found = forecast(nine_full_and_twenty_auto(), ReviewTier.AUTO)

    assert not found.prior
    assert found.usd is not None
