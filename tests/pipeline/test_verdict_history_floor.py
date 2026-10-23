"""The history floor reads the class's real record: brief-carrying samples against the gates
(spec: review-triage, the history floor; review-outcomes, a class clears the gates)."""

from __future__ import annotations

from typing import Any

from agent_build_kit.config import AutoLandConfig
from agent_build_kit.pipeline.verdict import ClassHistory, ReviewTier, TierVerdict, compute_verdict
from tests.review_records import by_unit, record
from tests.verdict_support import green_facts

AUTO, LIGHT, FULL = ReviewTier.AUTO, ReviewTier.LIGHT, ReviewTier.FULL
POLICY = AutoLandConfig(min_samples=20, min_clean_rate=0.95)


def clean(count: int, *, unit_class: str = "docs", brief: bool = True) -> list[dict]:
    return [record("clean", unit_class=unit_class, brief=brief)] * count


def verdict(records: dict[str, dict], **facts: Any) -> TierVerdict:
    history = ClassHistory.from_records(records, "docs")
    return compute_verdict(green_facts(**facts), history, POLICY)


def test_a_class_that_clears_the_gates_leaves_a_green_unit_at_auto() -> None:
    result = verdict(by_unit(*clean(20)))
    assert (result.tier, result.evidence_tier) == (AUTO, AUTO)


def test_a_class_with_one_rework_in_twenty_still_clears_the_gates() -> None:
    result = verdict(by_unit(*clean(19), record("reworked", unit_class="docs")))
    assert result.tier is AUTO


def test_a_class_with_three_samples_is_held_at_light_and_the_reason_names_the_shortfall() -> None:
    result = verdict(by_unit(*clean(3)))
    assert (result.tier, result.evidence_tier) == (LIGHT, AUTO)
    assert "3 samples" in result.reason
    assert "20" in result.reason


def test_a_class_of_thirty_clean_records_without_the_brief_is_held_at_light() -> None:
    result = verdict(by_unit(*clean(30, brief=False)))
    assert result.tier is LIGHT
    assert "0 samples" in result.reason


def test_the_records_of_another_class_are_no_history_of_this_one() -> None:
    result = verdict(by_unit(*clean(30, unit_class="code")))
    assert result.tier is LIGHT


def test_a_class_with_no_records_is_held_at_light() -> None:
    result = verdict({})
    assert (result.tier, result.evidence_tier) == (LIGHT, AUTO)


def test_a_clean_rate_below_the_gate_holds_the_class_at_light() -> None:
    result = verdict(by_unit(*clean(18), *[record("reverted", unit_class="docs")] * 2))
    assert result.tier is LIGHT
    assert "90%" in result.reason


def test_the_floor_never_lowers_a_tier_another_floor_set() -> None:
    proven = by_unit(*clean(20))
    assert verdict(proven, classification=FULL).tier is FULL
    assert verdict(proven, planned_estimate=FULL).tier is FULL
    assert verdict(by_unit(*clean(3)), classification=FULL).tier is FULL
