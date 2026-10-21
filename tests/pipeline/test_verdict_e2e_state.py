"""The verdict reads a unit's e2e result as one of four states, and a deferred one reaches `auto`
only when the policy allows it (spec: review-verdict-e2e-state)."""

from __future__ import annotations

from typing import Any

import pytest

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

AUTO, LIGHT, FULL = ReviewTier.AUTO, ReviewTier.LIGHT, ReviewTier.FULL
PROVEN = ClassHistory(samples=20, clean=20)
ALLOWING = AutoLandConfig.model_validate({"allow_deferred_e2e": True})
NO_FLOOR = "no recorded fact gives a floor above auto"


def facts(**changes: Any) -> VerdictFacts:
    """An e2e-test unit with every gate but the e2e result green; `changes` overrides a field."""
    base: dict[str, Any] = {
        "kind": TestTier.E2E_TEST,
        "red_first": GateResult.PASSED,
        "unit_test": GateResult.PASSED,
        "classification": AUTO,
        "final": True,
    }
    return VerdictFacts(**{**base, **changes})


@pytest.mark.parametrize(
    ("state", "tier"),
    [
        (E2eState.PASSED, AUTO),
        (E2eState.NOT_REQUIRED, AUTO),
        (E2eState.DEFERRED, LIGHT),
        (E2eState.FAILED, FULL),
    ],
)
def test_each_state_gives_its_floor_with_every_other_input_green(
    state: E2eState, tier: ReviewTier
) -> None:
    verdict = compute_verdict(facts(e2e_state=state), PROVEN)

    assert verdict.tier is tier
    assert verdict.evidence_tier is tier


def test_a_deferred_state_names_the_deferral_in_the_reason() -> None:
    verdict = compute_verdict(facts(e2e_state=E2eState.DEFERRED), PROVEN)

    assert verdict.reason == "the e2e-test result was deferred to verify"


def test_a_failed_state_names_the_failed_e2e_result() -> None:
    verdict = compute_verdict(facts(e2e_state=E2eState.FAILED), PROVEN)

    assert "e2e" in verdict.reason
    assert "failed" in verdict.reason


@pytest.mark.parametrize("state", [E2eState.PASSED, E2eState.NOT_REQUIRED])
def test_a_passed_or_not_required_state_adds_no_floor(state: E2eState) -> None:
    verdict = compute_verdict(facts(e2e_state=state), PROVEN)

    assert verdict.reason == NO_FLOOR


def test_the_allowance_makes_a_deferred_state_behave_as_passed() -> None:
    deferred = compute_verdict(facts(e2e_state=E2eState.DEFERRED), PROVEN, ALLOWING)
    passed = compute_verdict(facts(e2e_state=E2eState.PASSED), PROVEN, ALLOWING)

    assert deferred == passed
    assert deferred.tier is AUTO


def test_the_allowance_does_not_make_a_failed_state_pass() -> None:
    verdict = compute_verdict(facts(e2e_state=E2eState.FAILED), PROVEN, ALLOWING)

    assert verdict.tier is FULL


@pytest.mark.parametrize(
    "other",
    [
        {"protected_paths": ("Dockerfile",)},
        {"flags": ("contract",)},
        {"open_required_findings": 1},
    ],
    ids=["protected-path", "contract-flag", "open-finding"],
)
@pytest.mark.parametrize("policy", [AutoLandConfig(), ALLOWING], ids=["default", "allowing"])
def test_a_deferred_unit_with_another_floor_is_full_in_either_setting(
    other: dict[str, Any], policy: AutoLandConfig
) -> None:
    verdict = compute_verdict(facts(e2e_state=E2eState.DEFERRED, **other), PROVEN, policy)

    assert verdict.tier is FULL
    assert verdict.evidence_tier is FULL


def test_an_e2e_test_unit_with_no_state_is_a_missing_gate_in_the_final_verdict() -> None:
    verdict = compute_verdict(facts(e2e_state=None, final=True), PROVEN)

    assert verdict.tier is FULL
    assert verdict.reason == "the e2e-test gate has no result"


def test_an_e2e_test_unit_with_no_state_adds_no_floor_in_an_interim_verdict() -> None:
    verdict = compute_verdict(facts(e2e_state=None, final=False), PROVEN)

    assert verdict.tier is AUTO


def test_a_unit_test_unit_with_no_state_is_read_as_not_required() -> None:
    verdict = compute_verdict(facts(kind=TestTier.UNIT_TEST, e2e_state=None), PROVEN)

    assert verdict.tier is AUTO
    assert verdict.reason == NO_FLOOR


def test_the_same_facts_give_the_same_answer_twice() -> None:
    for state in (*E2eState, None):
        first = compute_verdict(facts(e2e_state=state), PROVEN)
        assert compute_verdict(facts(e2e_state=state), PROVEN) == first, state
