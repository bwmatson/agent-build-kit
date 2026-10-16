"""The `modal` row turns the billing summary into a reading, or into unknown."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest

from agent_build_kit.runtimes.providers import ProviderReading, ProviderUnknown, read_usage

NOW = datetime(2026, 10, 14, 9, 0, tzinfo=UTC)
START = datetime(2026, 10, 1, tzinfo=UTC)
END = datetime(2026, 11, 1, tzinfo=UTC)


def summary(**overrides: object) -> SimpleNamespace:
    """The fields the library's billing summary carries."""
    fields: dict[str, object] = {
        "start": START,
        "end": END,
        "metered_cost": Decimal("173.04285316"),
        "metered_cost_breakdown": {"object-1": Decimal("100"), "object-2": Decimal("73.04285316")},
        "adjustments": [{"credit": Decimal("30")}],
        "billed_cost": Decimal("142.99"),
    }
    fields.update(overrides)
    return SimpleNamespace(**fields)


def reading(given: SimpleNamespace, *, now: datetime = NOW) -> ProviderReading:
    result = read_usage("modal", budget_usd=200, now=now, read=lambda: given)
    assert isinstance(result, ProviderReading), result
    return result


def test_the_used_percent_is_metered_cost_over_the_budget_rounded_up() -> None:
    result = reading(summary())

    assert result.used_amount == Decimal("173.04285316")
    assert result.used_pct == 87


@pytest.mark.parametrize(
    ("cost", "pct"), [(Decimal("2.3E-7"), 1), (Decimal(0), 0), (Decimal(250), 125)]
)
def test_a_tiny_amount_rounds_up_zero_stays_zero_and_over_budget_is_not_capped(
    cost: Decimal, pct: int
) -> None:
    assert reading(summary(metered_cost=cost)).used_pct == pct


def test_billed_cost_adjustments_and_the_breakdown_change_nothing() -> None:
    plain = reading(summary(billed_cost=Decimal(0), adjustments=[], metered_cost_breakdown={}))
    busy = reading(
        summary(billed_cost=Decimal("1"), adjustments=[1, 2], metered_cost_breakdown={1: 2})
    )

    assert plain == busy


def test_the_window_is_the_summarys_start_and_end() -> None:
    result = reading(summary())

    assert (result.window_start, result.window_end) == (START, END)


def test_a_clock_at_the_end_is_outside_the_window() -> None:
    result = reading(summary(), now=END)

    assert result.window_start <= NOW < result.window_end
    assert not (result.window_start <= END < result.window_end)


@pytest.mark.parametrize("missing", ["start", "end"])
@pytest.mark.parametrize("how", ["none", "absent"])
@pytest.mark.parametrize(
    ("now", "start", "end"),
    [
        (NOW, datetime(2026, 10, 1, tzinfo=UTC), datetime(2026, 11, 1, tzinfo=UTC)),
        (
            datetime(2026, 12, 31, 23, 30, tzinfo=UTC),
            datetime(2026, 12, 1, tzinfo=UTC),
            datetime(2027, 1, 1, tzinfo=UTC),
        ),
        (
            datetime(2028, 2, 10, tzinfo=UTC),
            datetime(2028, 2, 1, tzinfo=UTC),
            datetime(2028, 3, 1, tzinfo=UTC),
        ),
    ],
)
def test_a_summary_without_a_start_or_an_end_falls_back_to_the_calendar_month_in_utc(
    missing: str, how: str, now: datetime, start: datetime, end: datetime
) -> None:
    given = summary(**{missing: None})
    if how == "absent":
        delattr(given, missing)

    result = reading(given, now=now)

    assert (result.window_start, result.window_end) == (start, end)


def test_the_fallback_month_is_the_utc_month_of_a_clock_in_another_zone() -> None:
    from datetime import timedelta, timezone

    late_in_the_evening = datetime(2026, 10, 31, 22, 0, tzinfo=timezone(timedelta(hours=-5)))

    result = reading(summary(start=None), now=late_in_the_evening)

    assert (result.window_start, result.window_end) == (
        datetime(2026, 11, 1, tzinfo=UTC),
        datetime(2026, 12, 1, tzinfo=UTC),
    )


def test_a_missing_metered_cost_is_unknown_and_says_so() -> None:
    given = summary()
    del given.metered_cost

    result = read_usage("modal", budget_usd=200, now=NOW, read=lambda: given)

    assert isinstance(result, ProviderUnknown)
    assert "metered_cost" in result.reason


@pytest.mark.parametrize("bad", ["abc", -3, Decimal("-3"), None])
def test_a_metered_cost_that_is_not_a_non_negative_decimal_is_unknown(bad: object) -> None:
    result = read_usage("modal", budget_usd=200, now=NOW, read=lambda: summary(metered_cost=bad))

    assert isinstance(result, ProviderUnknown)
    assert "metered_cost" in result.reason
    if isinstance(bad, str | int):
        assert str(bad) in result.reason
