"""The verdict names the rule that decided it (spec: review-verdict, deterministic verdict)."""

from __future__ import annotations

from agent_build_kit.pipeline.verdict import ReviewTier, compute_verdict
from tests.verdict_support import green_facts


def test_a_protected_path_decides_and_is_named() -> None:
    facts = green_facts(protected_paths=("db/migrations/001.sql",))

    assert "db/migrations/001.sql" in compute_verdict(facts).reason


def test_a_flag_decides_and_is_named() -> None:
    facts = green_facts(flags=("contract",))

    assert "contract" in compute_verdict(facts).reason


def test_the_planned_estimate_decides_and_the_reason_says_so() -> None:
    facts = green_facts(planned_estimate=ReviewTier.LIGHT)

    reason = compute_verdict(facts).reason
    assert "planned" in reason
    assert "light" in reason


def test_a_higher_floor_beats_a_lower_one_in_the_reason() -> None:
    facts = green_facts(planned_estimate=ReviewTier.LIGHT, flags=("acceptance",))

    assert "acceptance" in compute_verdict(facts).reason


def test_equal_floors_name_the_planned_estimate_before_the_protected_path() -> None:
    facts = green_facts(
        planned_estimate=ReviewTier.FULL, protected_paths=("Dockerfile",), flags=("narrow",)
    )

    reason = compute_verdict(facts).reason
    assert "planned" in reason
    assert "Dockerfile" not in reason
    assert "narrow" not in reason


def test_equal_floors_name_the_protected_path_before_the_flag() -> None:
    facts = green_facts(protected_paths=("Dockerfile",), flags=("narrow",))

    reason = compute_verdict(facts).reason
    assert "Dockerfile" in reason
    assert "narrow" not in reason
