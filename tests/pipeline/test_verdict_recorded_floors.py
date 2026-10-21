"""The verdict's floors from the recorded gate results, the review and the class's history
(spec: review-verdict, deterministic verdict).

Each test loops over its cases, so a test that fails names the case that did it."""

from __future__ import annotations

from agent_build_kit.config import AutoLandConfig
from agent_build_kit.model import TestTier
from agent_build_kit.pipeline.unit_store import E2eState
from agent_build_kit.pipeline.verdict import (
    ClassHistory,
    GateResult,
    ReviewTier,
    VerdictFacts,
    compute_verdict,
)
from tests.verdict_support import green_facts

AUTO, LIGHT, FULL = ReviewTier.AUTO, ReviewTier.LIGHT, ReviewTier.FULL
PASSED, FAILED, MISSING, PENDING = (
    GateResult.PASSED,
    GateResult.FAILED,
    GateResult.MISSING,
    GateResult.PENDING,
)

PROVEN = ClassHistory(samples=20, clean=20)

# Case name to the facts and the evidence tier they give alone.
EVIDENCE_CASES: dict[str, tuple[VerdictFacts, ReviewTier]] = {
    "red-first-missing": (green_facts(red_first=MISSING), FULL),
    "red-first-failed": (green_facts(red_first=FAILED), FULL),
    "unit-test-missing": (green_facts(unit_test=MISSING), FULL),
    "unit-test-failed": (green_facts(unit_test=FAILED), FULL),
    "e2e-test-missing": (
        green_facts(kind=TestTier.E2E_TEST, e2e_state=None, final=True),
        FULL,
    ),
    "e2e-test-failed": (green_facts(kind=TestTier.E2E_TEST, e2e_state=E2eState.FAILED), FULL),
    "open-required-finding": (green_facts(open_required_findings=1), FULL),
    "classified-light": (green_facts(classification=LIGHT), LIGHT),
    "classified-full": (green_facts(classification=FULL), FULL),
    "no-classification": (green_facts(classification=None), FULL),
    "classification-cannot-lower-the-estimate": (
        green_facts(planned_estimate=LIGHT, classification=AUTO),
        LIGHT,
    ),
    "classification-raises-the-estimate": (
        green_facts(planned_estimate=AUTO, classification=LIGHT),
        LIGHT,
    ),
    "light-and-failed-gate": (green_facts(classification=LIGHT, unit_test=FAILED), FULL),
    "several-floors": (
        green_facts(
            planned_estimate=LIGHT,
            protected_paths=("Dockerfile",),
            red_first=MISSING,
            open_required_findings=2,
            classification=None,
        ),
        FULL,
    ),
}


def test_the_evidence_tier_is_the_highest_floor_from_the_recorded_facts() -> None:
    for name, (facts, expected) in EVIDENCE_CASES.items():
        assert compute_verdict(facts, PROVEN).evidence_tier is expected, name


def test_a_proven_class_gives_the_tier_the_evidence_gives() -> None:
    for name, (facts, expected) in EVIDENCE_CASES.items():
        assert compute_verdict(facts, PROVEN).tier is expected, name


def test_every_case_that_must_not_reach_auto_does_not() -> None:
    assert compute_verdict(green_facts(), PROVEN).tier is AUTO
    for name, (facts, _) in EVIDENCE_CASES.items():
        assert compute_verdict(facts, PROVEN).tier is not AUTO, name


def test_a_class_without_a_track_record_is_held_at_light_and_the_evidence_tier_is_not() -> None:
    thin = [
        ClassHistory(),
        ClassHistory(samples=19, clean=19),
        ClassHistory(samples=20, clean=18),
        ClassHistory(samples=100, clean=94),
    ]
    for history in thin:
        verdict = compute_verdict(green_facts(), history)
        assert verdict.evidence_tier is AUTO, history
        assert verdict.tier is LIGHT, history

    enough = [ClassHistory(samples=20, clean=19), ClassHistory(samples=50, clean=50)]
    for history in enough:
        assert compute_verdict(green_facts(), history).tier is AUTO, history


def test_a_class_with_too_few_samples_says_so() -> None:
    verdict = compute_verdict(green_facts(), ClassHistory(samples=3, clean=3))

    assert "samples" in verdict.reason


def test_a_class_with_a_low_clean_rate_says_so() -> None:
    verdict = compute_verdict(green_facts(), ClassHistory(samples=20, clean=10))

    assert "clean" in verdict.reason
    assert "samples" not in verdict.reason


def test_the_policy_sets_the_sample_count_and_the_clean_rate() -> None:
    history = ClassHistory(samples=5, clean=4)
    strict = AutoLandConfig()
    lenient = AutoLandConfig(min_samples=5, min_clean_rate=0.8)

    assert compute_verdict(green_facts(), history, strict).tier is LIGHT
    assert compute_verdict(green_facts(), history, lenient).tier is AUTO


def test_the_e2e_gate_decides_only_for_a_unit_of_the_e2e_kind() -> None:
    for result in (None, E2eState.FAILED, E2eState.DEFERRED):
        for kind in (TestTier.UNIT_TEST, TestTier.INTEGRATION_TEST):
            facts = green_facts(kind=kind, e2e_state=result, final=True)
            assert compute_verdict(facts, PROVEN).tier is AUTO, (kind, result)
    for result in (None, E2eState.FAILED):
        facts = green_facts(kind=TestTier.E2E_TEST, e2e_state=result, final=True)
        assert compute_verdict(facts, PROVEN).tier is FULL, result


def test_a_pending_gate_is_met_in_an_interim_verdict_and_missing_in_the_final_one() -> None:
    interim = green_facts(kind=TestTier.E2E_TEST, e2e_state=None)
    final = interim.model_copy(update={"final": True})

    assert compute_verdict(interim, PROVEN).tier is AUTO
    assert compute_verdict(final, PROVEN).tier is FULL
    assert "no result" in compute_verdict(final, PROVEN).reason


def test_a_missing_gate_is_full_and_the_reason_says_it_has_no_result() -> None:
    red_first = compute_verdict(green_facts(red_first=MISSING), PROVEN)
    unit_test = compute_verdict(green_facts(unit_test=MISSING), PROVEN)

    assert red_first.tier is FULL
    assert "no result" in red_first.reason
    assert "red-first" in red_first.reason
    assert unit_test.tier is FULL
    assert "no result" in unit_test.reason
    assert "unit-test" in unit_test.reason


def test_a_failed_gate_is_full_and_the_reason_says_it_failed() -> None:
    verdict = compute_verdict(green_facts(unit_test=FAILED), PROVEN)

    assert verdict.tier is FULL
    assert "failed" in verdict.reason


def test_an_open_required_finding_is_named() -> None:
    verdict = compute_verdict(green_facts(open_required_findings=1), PROVEN)

    assert verdict.tier is FULL
    assert "finding" in verdict.reason


def test_a_missing_classification_is_named() -> None:
    verdict = compute_verdict(green_facts(classification=None), PROVEN)

    assert verdict.tier is FULL
    assert "classification" in verdict.reason


def test_an_auto_verdict_names_no_single_source_for_its_reason() -> None:
    verdict = compute_verdict(green_facts(), PROVEN)

    assert verdict.tier is AUTO
    assert "no recorded fact" in verdict.reason
