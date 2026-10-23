"""A unit about to start is forecast in dollars and points by the sum over its tier's cells
(spec: usage-pause)."""

import pytest

from agent_build_kit.pipeline.usage_forecast_unit import UnitForecast, forecast_unit
from agent_build_kit.pipeline.verdict import ReviewTier
from tests.usage_forecast_fixtures import spec_history


def forecast(tier: ReviewTier) -> UnitForecast:
    history = spec_history()
    return forecast_unit(
        history.records,
        history.verdicts,
        tier=tier,
        estimated_lines=10,
        points_per_usd=2.5,
        flat_allowance=11,
        min_runs=5,
        quantile=0.5,
    )


def test_an_auto_unit_is_forecast_at_the_spec_figures() -> None:
    found = forecast(ReviewTier.AUTO)

    assert not found.prior
    assert found.usd == pytest.approx(2.55)
    assert found.points == pytest.approx(6.4, abs=0.05)


def test_a_full_unit_is_forecast_at_the_spec_figures() -> None:
    found = forecast(ReviewTier.FULL)

    assert found.usd == pytest.approx(3.42)
    assert found.points == pytest.approx(8.6, abs=0.05)


def test_no_rework_cell_is_in_the_auto_sum() -> None:
    assert "rework" not in {part.node for part in forecast(ReviewTier.AUTO).parts}


def test_the_review_part_of_a_full_unit_is_not_three_rounds_at_the_first() -> None:
    parts = forecast(ReviewTier.FULL).parts

    assert sum(p.usd for p in parts if p.node == "review") == pytest.approx(1.57)


def test_the_parts_come_to_the_forecast() -> None:
    found = forecast(ReviewTier.FULL)

    assert sum(p.usd for p in found.parts) == pytest.approx(found.usd or 0)
