"""The allowance of each window is calibrated from the readings and ledger on disk.

Pairs are consecutive good readings with a unit's spend between them; the allowance is a
high quantile of points gained per unit over the newest pairs, between a floor and a
ceiling, and only with enough pairs (spec: usage-pause)."""

from datetime import UTC, datetime, timedelta

from agent_build_kit.config import ClaudeLimitsConfig
from agent_build_kit.pipeline.usage_allowances import (
    Calibrated,
    allowance_for,
    calibrated_allowances,
    pairs,
)
from tests.usage_allowance_records import (
    GAP,
    MIN_GAP,
    START,
    per_unit,
    reading,
    segments,
    spend,
)

NOW = datetime(2026, 11, 1, tzinfo=UTC)
WEEKLY_GAINS = [0, 0, 0.5, 0.5, 0.5, 1, 1, 0.5, 0, 1, 0.5, 2]


def limits(**values: object) -> ClaudeLimitsConfig:
    return ClaudeLimitsConfig.model_validate(values)


def found(window: str, calls: list, ledger: list, **settings: object) -> Calibrated | None:
    return calibrated_allowances(calls, ledger, limits=limits(**settings), now=NOW).get(window)


def kept(raw: float | None, *, pairs_used: int = 12) -> Calibrated:
    return Calibrated(
        quantile_pct_per_unit=raw,
        quantile=0.9,
        pairs_used=pairs_used,
        pairs_available=pairs_used,
        computed_at=NOW,
    )


# --- 1.1 pairs ---------------------------------------------------------------------------


def test_two_good_readings_with_a_spending_unit_between_them_are_a_pair() -> None:
    calls, ledger = segments("weekly", [(3, 2)])

    made = pairs(calls, ledger, "weekly", min_gap=MIN_GAP)

    assert [(p.at, p.gain, p.units) for p in made] == [(START, 3, 2)]


def test_a_fall_makes_no_pair() -> None:
    calls, ledger = segments("weekly", [(0, 1)])
    calls[1] = reading("weekly", START + GAP, 4)

    assert pairs(calls, ledger, "weekly", min_gap=MIN_GAP) == []


def test_a_gap_longer_than_the_span_of_the_window_makes_no_pair() -> None:
    session, session_ledger = segments("session", [(3, 1)], gap=timedelta(hours=6))
    weekly, weekly_ledger = segments("weekly", [(3, 1)], gap=timedelta(hours=6))

    assert pairs(session, session_ledger, "session", min_gap=MIN_GAP) == []
    assert len(pairs(weekly, weekly_ledger, "weekly", min_gap=MIN_GAP)) == 1


def test_a_gap_with_no_unit_that_spent_makes_no_pair() -> None:
    calls, _ = segments("weekly", [(3, 1)])

    assert pairs(calls, [], "weekly", min_gap=MIN_GAP) == []


def test_readings_less_than_the_cache_time_apart_make_no_pair() -> None:
    calls = [reading("weekly", START, 10), reading("weekly", START + timedelta(minutes=10), 12)]
    ledger = [spend("u", START + timedelta(minutes=5))]

    assert pairs(calls, ledger, "weekly", min_gap=MIN_GAP) == []


def test_rows_without_a_percentage_or_that_are_not_good_readings_make_no_pair() -> None:
    calls, ledger = segments("weekly", [(3, 1)])
    between = START + GAP / 2
    noise = [
        reading("weekly", between, None),
        reading("weekly", between, 99, outcome="cache"),
        reading("weekly", between, 99, outcome="rate_limited"),
        reading("session", between, 50),
    ]

    made = pairs(calls + noise, ledger, "weekly", min_gap=MIN_GAP)

    assert [(p.gain, p.units) for p in made] == [(3, 1)]


def test_units_are_counted_by_id_from_the_earlier_reading_up_to_the_later_one() -> None:
    calls, _ = segments("weekly", [(3, 1)])
    ledger = [
        spend("a", START),  # at the earlier reading: in
        spend("a", START + GAP / 4, node="review"),  # the same unit again: once
        spend("b", START + GAP / 2),
        spend("c", START + GAP),  # at the later reading: out
        spend("d", START - timedelta(minutes=1)),  # before: out
    ]

    made = pairs(calls, ledger, "weekly", min_gap=MIN_GAP)

    assert [p.units for p in made] == [2]


# --- 1.2 the worked cases ----------------------------------------------------------------


def test_twelve_weekly_pairs_gaining_little_give_one_point_a_unit_at_the_ninetieth() -> None:
    calls, ledger = per_unit("weekly", WEEKLY_GAINS)

    result = found("weekly", calls, ledger)

    assert result is not None
    assert (result.quantile_pct_per_unit, result.pairs_used, result.pairs_available) == (1, 12, 12)
    assert allowance_for("weekly", result, limits()) == 1


def test_ten_session_pairs_costing_more_than_the_default_give_a_figure_above_it() -> None:
    calls, ledger = per_unit("session", [11, 12, 13, 14, 11, 12, 13, 14, 11, 12], units=1)

    result = found("session", calls, ledger)

    assert 10 < allowance_for("session", result, limits()) <= 20


# --- 1.3 window, minimum, floor and ceiling ----------------------------------------------


def test_only_the_newest_pairs_in_the_window_count() -> None:
    calls, ledger = per_unit("weekly", [10] * 6 + [1, 1, 1, 2], units=1)

    result = found("weekly", calls, ledger, usage_allowance_window=4, usage_allowance_min_pairs=2)

    assert result is not None
    assert (result.quantile_pct_per_unit, result.pairs_used, result.pairs_available) == (2, 4, 10)


def test_seven_pairs_against_a_minimum_of_eight_apply_nothing() -> None:
    calls, ledger = per_unit("weekly", [0.5] * 7)

    result = found("weekly", calls, ledger)

    assert result is not None
    assert (result.quantile_pct_per_unit, result.pairs_available) == (None, 7)
    assert allowance_for("weekly", result, limits()) == 2


def test_eight_pairs_apply() -> None:
    calls, ledger = per_unit("weekly", [3] * 8)

    result = found("weekly", calls, ledger)

    assert result is not None
    assert result.quantile_pct_per_unit == 3


def test_the_floor_raises_a_zero_quantile_to_one() -> None:
    assert allowance_for("weekly", kept(0), limits()) == 1


def test_the_floor_is_the_one_set_for_the_window() -> None:
    configured = limits(weekly={"usage_allowance_floor_pct": 2})

    assert allowance_for("weekly", kept(0), configured) == 2


def test_the_ceiling_is_twice_the_default_when_the_allowance_is_auto() -> None:
    auto = limits(
        session={"usage_unit_allowance_pct": "auto"}, weekly={"usage_unit_allowance_pct": "auto"}
    )

    assert allowance_for("session", kept(40), auto) == 20
    assert allowance_for("weekly", kept(40), auto) == 4


def test_an_explicit_allowance_is_the_cap_and_a_lower_figure_stands() -> None:
    capped = limits(weekly={"usage_unit_allowance_pct": 3})

    assert allowance_for("weekly", kept(5), capped) == 3
    assert allowance_for("weekly", kept(1), capped) == 1


def test_a_figure_between_the_bounds_is_rounded_up_to_whole_points() -> None:
    assert allowance_for("session", kept(8.2), limits()) == 9


def test_calibration_off_uses_the_configured_allowance_of_every_window() -> None:
    off = limits(calibrate_usage_allowances=False, weekly={"usage_unit_allowance_pct": 3})

    assert allowance_for("session", kept(15), off) == 10
    assert allowance_for("weekly", kept(1), off) == 3
    assert calibrated_allowances(*per_unit("weekly", [1] * 9), limits=off, now=NOW) == {}


def test_a_window_with_no_calibration_has_its_configured_allowance() -> None:
    assert allowance_for("session", None, limits()) == 10
    assert allowance_for("weekly", None, limits()) == 2
