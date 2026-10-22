"""A cost pair is a gap of two good readings that holds recorded cost, with a unit or without
one; a flat pair is a gap that holds a unit, whatever it cost (spec: usage-pause)."""

from datetime import timedelta

import pytest

from agent_build_kit.pipeline.usage_allowances import (
    CostPair,
    UsagePair,
    Window,
    cost_pairs,
    pairs,
)
from agent_build_kit.pipeline.usage_calls import UsageCall
from agent_build_kit.pipeline.usage_ledger import UsageRecord
from tests.usage_allowance_records import MIN_GAP, START, reading
from tests.usage_cost_records import row

MIDDLE = START + timedelta(hours=1)


def readings(
    window: Window = "session", *, before: int = 10, after: int = 15, hours: float = 2.0
) -> list[UsageCall]:
    return [
        reading(window, START, before),
        reading(window, START + timedelta(hours=hours), after),
    ]


def cost_made(
    calls: list[UsageCall], ledger: list[UsageRecord], window: Window = "session"
) -> list[CostPair]:
    return cost_pairs(calls, ledger, window, min_gap=MIN_GAP)


def test_a_gap_with_only_a_plan_row_is_a_cost_pair_and_not_a_flat_pair() -> None:
    ledger = [row(MIDDLE, unit="", node="plan", cost=1.5)]

    assert cost_made(readings(), ledger) == [
        CostPair(at=START, before=10, gain=5, cost_usd=1.5, hours=2.0, units=0)
    ]
    assert pairs(readings(), ledger, "session", min_gap=MIN_GAP) == []


def test_a_gap_with_a_unit_is_both_and_the_flat_pair_is_what_it_was() -> None:
    ledger = [
        row(MIDDLE, unit="app/a", node="implement", cost=1.0),
        row(MIDDLE, unit="app/a", node="review", cost=0.5),
        row(MIDDLE, unit="", node="plan", cost=0.25),
    ]

    assert pairs(readings(), ledger, "session", min_gap=MIN_GAP) == [
        UsagePair(at=START, before=10, gain=5, units=1)
    ]
    assert cost_made(readings(), ledger) == [
        CostPair(at=START, before=10, gain=5, cost_usd=1.75, hours=2.0, units=1)
    ]


def test_a_unit_with_a_row_that_has_a_cost_and_one_that_has_none_counts_its_cost() -> None:
    ledger = [
        row(MIDDLE, unit="app/a", node="implement", cost=1.0),
        row(MIDDLE, unit="app/a", node="review", cost=None),
    ]

    assert [(p.cost_usd, p.units) for p in cost_made(readings(), ledger)] == [(1.0, 1)]


@pytest.mark.parametrize(
    "ledger",
    [
        pytest.param([row(MIDDLE, unit="", node="login_refresh", cost=None)], id="login-refresh"),
        pytest.param([], id="no-row"),
        pytest.param(
            [
                row(MIDDLE, unit="app/a", node="implement", cost=None),
                row(MIDDLE, unit="app/a", node="review", cost=None),
            ],
            id="unit-without-a-cost",
        ),
        pytest.param(
            [
                row(MIDDLE, unit="app/a", node="implement", cost=1.0),
                row(MIDDLE, unit="app/b", node="implement", cost=None),
            ],
            id="one-unit-without-a-cost",
        ),
        pytest.param([row(MIDDLE, unit="", node="plan", cost=0.0)], id="cost-of-zero"),
    ],
)
def test_a_gap_that_holds_no_cost_or_a_unit_without_one_is_not_a_cost_pair(
    ledger: list[UsageRecord],
) -> None:
    assert cost_made(readings(), ledger) == []


@pytest.mark.parametrize(
    ("window", "kwargs"),
    [
        pytest.param("session", {"before": 20, "after": 15}, id="lower-later-figure"),
        pytest.param("session", {"hours": 0.2}, id="closer-than-the-cache-time"),
        pytest.param("session", {"hours": 6.0}, id="longer-than-the-session"),
        pytest.param("weekly", {"hours": 8 * 24.0}, id="longer-than-the-week"),
    ],
)
def test_readings_that_are_not_a_pair_make_no_cost_pair(window: Window, kwargs: dict) -> None:
    ledger = [row(START + timedelta(minutes=6), unit="", node="plan", cost=1.0)]

    assert cost_made(readings(window, **kwargs), ledger, window) == []


def test_a_row_at_the_earlier_reading_is_in_the_gap_and_one_at_the_later_is_not() -> None:
    at_earlier = [row(START, unit="", node="plan", cost=1.0)]
    at_later = [row(START + timedelta(hours=2), unit="", node="plan", cost=1.0)]

    assert [p.cost_usd for p in cost_made(readings(), at_earlier)] == [1.0]
    assert cost_made(readings(), at_later) == []
