"""A row with no unit is spend, not a unit: the estimate and the calibration count units
(spec: usage-pause, a blank unit is never counted as a unit).
"""

from __future__ import annotations

import pytest

from agent_build_kit.pipeline.usage_allowances import pairs
from agent_build_kit.pipeline.usage_guard import decide_start
from tests.pipeline.test_usage_estimate import HOUR, MINUTE, seventy, spent, thresholds
from tests.usage_allowance_records import GAP, MIN_GAP, START, gaps, spend
from tests.usage_host import Host


@pytest.fixture(autouse=True)
def ninety_two() -> None:
    thresholds()


def test_a_unit_with_a_row_since_the_reading_counts_and_the_blank_unit_does_not(
    host: Host,
) -> None:
    seventy(host)
    spent(host, "feature/1", HOUR)
    spent(host, "", 50 * MINUTE, 40 * MINUTE)

    decision = decide_start(unit="feature/9")

    assert decision.may_start
    assert "session ~80% estimated (70% read + 10% spent)" in decision.reason


def test_rows_with_only_the_blank_unit_since_the_reading_add_no_allowance(host: Host) -> None:
    seventy(host)
    spent(host, "", HOUR, 30 * MINUTE)

    decision = decide_start(unit="feature/9")

    assert decision.may_start
    assert "session ~70% estimated (70% read + 0% spent)" in decision.reason


def test_a_gap_in_which_only_the_blank_unit_spent_makes_no_calibration_pair() -> None:
    calls, ledger = gaps("weekly", [(10, 14, 0)])
    ledger.append(spend("", START + GAP / 2, node="plan"))

    assert pairs(calls, ledger, "weekly", min_gap=MIN_GAP) == []


def test_a_gaps_units_skip_the_blank_unit() -> None:
    calls, ledger = gaps("weekly", [(10, 14, 2)])
    ledger.append(spend("", START + GAP / 2, node="plan"))
    ledger.append(spend("", START + GAP / 3, node="track_health"))

    (made,) = pairs(calls, ledger, "weekly", min_gap=MIN_GAP)

    assert made.units == 2
