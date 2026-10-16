"""A provider's month is judged by the threshold ramp the Claude Code windows use."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from agent_build_kit.config import GateConfig
from agent_build_kit.pipeline.usage_guard import GateResult, gate_result, provider_decision
from agent_build_kit.runtimes.providers import ProviderReading
from tests.provider_gate_support import before_end, gate, limits, reading
from tests.provider_summaries import END, START, summary

TEN_DAYS_IN = START + timedelta(days=10)
# The ramp covers 7.75 days; this many days from the end the threshold is 85 (a quarter of the
# span to go) and 84 (three tenths of it).
THRESHOLD_85 = before_end(timedelta(days=1.9375))
THRESHOLD_84 = before_end(timedelta(days=2.325))


def test_before_the_ramp_the_threshold_is_the_pause_percent_and_over_it_the_split_is_held() -> None:
    result = provider_decision(reading(87), limits=limits(), now=TEN_DAYS_IN)

    assert (result.state, result.threshold, result.used_pct) == ("held", 70, 87)
    assert result.until == END


def test_under_the_pause_percent_the_split_is_usable() -> None:
    result = provider_decision(reading(40), limits=limits(), now=TEN_DAYS_IN)

    assert (result.state, result.threshold) == ("usable", 70)


def test_a_quarter_of_the_ramp_to_go_the_threshold_is_85_and_87_is_held() -> None:
    result = provider_decision(reading(87), limits=limits(), now=THRESHOLD_85)

    assert (result.state, result.threshold) == ("held", 85)


def test_half_a_day_before_the_end_the_threshold_is_89_and_80_is_usable() -> None:
    result = provider_decision(reading(80), limits=limits(), now=before_end(timedelta(hours=12)))

    assert (result.state, result.threshold) == ("usable", 89)


def test_a_second_before_the_end_the_threshold_is_the_ceiling() -> None:
    result = provider_decision(reading(50), limits=limits(), now=before_end(timedelta(seconds=1)))

    assert result.threshold == 90


def test_with_no_ceiling_the_threshold_is_the_pause_percent_throughout() -> None:
    flat = limits(ceiling=None)

    thresholds = {
        provider_decision(reading(10), limits=flat, now=now).threshold
        for now in (TEN_DAYS_IN, THRESHOLD_85, before_end(timedelta(hours=1)))
    }

    assert thresholds == {70}


def test_a_standing_hold_stands_at_84_and_lifts_at_85_with_a_buffer_of_5() -> None:
    standing = provider_decision(reading(80), limits=limits(), now=THRESHOLD_84, standing=True)
    lifted = provider_decision(reading(80), limits=limits(), now=THRESHOLD_85, standing=True)

    assert (standing.threshold, standing.state) == (84, "held")
    assert (lifted.threshold, lifted.state) == (85, "usable")


def test_a_hold_that_is_not_standing_begins_at_the_threshold_not_the_buffer_line() -> None:
    below = provider_decision(reading(83), limits=limits(), now=THRESHOLD_84)
    at = provider_decision(reading(84), limits=limits(), now=THRESHOLD_84)

    assert (below.state, at.state) == ("usable", "held")


@pytest.mark.parametrize("elapsed", [timedelta(0), timedelta(seconds=1), timedelta(days=3)])
def test_a_reading_is_not_used_at_or_after_its_window_end(elapsed: timedelta) -> None:
    result = provider_decision(reading(95), limits=limits(), now=END + elapsed)

    assert result.state == "unknown"
    assert result.reason


def test_usage_is_never_estimated_forward() -> None:
    early = provider_decision(reading(60), limits=limits(), now=TEN_DAYS_IN)
    late = provider_decision(reading(60), limits=limits(), now=before_end(timedelta(hours=1)))

    assert (early.used_pct, late.used_pct) == (60, 60)


def test_raising_the_budget_turns_87_percent_into_44_and_lifts_the_hold(tmp_path: Path) -> None:
    def spent() -> object:
        return summary()  # a metered cost of 173.04285316

    def judged(config: GateConfig) -> GateResult:
        return gate_result(
            "acp",
            config,
            now=TEN_DAYS_IN,
            state_dir=tmp_path,
            root=tmp_path,
            standing=True,
            refresh=True,
            read=spent,
        )

    at_200 = judged(gate(budget=200))
    at_400 = judged(gate(budget=400))

    assert (at_200.used_pct, at_200.state) == (87, "held")
    assert (at_400.used_pct, at_400.state) == (44, "usable")


def test_a_reading_carries_its_amount_into_the_result() -> None:
    given = ProviderReading(
        used_amount=Decimal("173.04285316"), used_pct=87, window_start=START, window_end=END
    )

    result = provider_decision(given, limits=limits(), now=TEN_DAYS_IN)

    assert result.used_amount == Decimal("173.04285316")
    assert result.window_end == END
