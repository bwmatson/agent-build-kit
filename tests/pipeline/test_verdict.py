"""The verdict's floors from the plan alone (spec: review-verdict, deterministic verdict)."""

from __future__ import annotations

import pytest

from agent_build_kit.model import TestTier
from agent_build_kit.pipeline.verdict import ReviewTier, VerdictFacts, compute_verdict

AUTO, LIGHT, FULL = ReviewTier.AUTO, ReviewTier.LIGHT, ReviewTier.FULL

CASES = [
    pytest.param(VerdictFacts(kind=TestTier.UNIT_TEST), AUTO, id="no-floor"),
    pytest.param(VerdictFacts(kind=TestTier.UNIT_TEST, planned_estimate=AUTO), AUTO, id="auto"),
    pytest.param(VerdictFacts(kind=TestTier.UNIT_TEST, planned_estimate=LIGHT), LIGHT, id="light"),
    pytest.param(VerdictFacts(kind=TestTier.UNIT_TEST, planned_estimate=FULL), FULL, id="full"),
    pytest.param(
        VerdictFacts(kind=TestTier.UNIT_TEST, protected_paths=("db/migrations/001.sql",)),
        FULL,
        id="protected-path",
    ),
    pytest.param(VerdictFacts(kind=TestTier.UNIT_TEST, flags=("contract",)), FULL, id="contract"),
    pytest.param(VerdictFacts(kind=TestTier.UNIT_TEST, flags=("narrow",)), FULL, id="narrow"),
    pytest.param(
        VerdictFacts(kind=TestTier.UNIT_TEST, flags=("acceptance",)), FULL, id="acceptance"
    ),
    pytest.param(
        VerdictFacts(kind=TestTier.UNIT_TEST, planned_estimate=LIGHT, flags=("contract",)),
        FULL,
        id="light-and-flag",
    ),
    pytest.param(
        VerdictFacts(
            kind=TestTier.UNIT_TEST, planned_estimate=AUTO, protected_paths=("Dockerfile",)
        ),
        FULL,
        id="auto-and-path",
    ),
    pytest.param(
        VerdictFacts(
            kind=TestTier.UNIT_TEST,
            planned_estimate=FULL,
            protected_paths=("Dockerfile",),
            flags=("narrow",),
        ),
        FULL,
        id="all-three",
    ),
]


@pytest.mark.parametrize(("facts", "expected"), CASES)
def test_the_evidence_tier_is_the_highest_floor_from_the_plan(
    facts: VerdictFacts, expected: ReviewTier
) -> None:
    assert compute_verdict(facts).evidence_tier is expected


@pytest.mark.parametrize(("facts", "expected"), CASES)
def test_an_integration_test_unit_gets_the_floors_a_unit_test_unit_gets(
    facts: VerdictFacts, expected: ReviewTier
) -> None:
    as_integration = facts.model_copy(update={"kind": TestTier.INTEGRATION_TEST})

    assert compute_verdict(as_integration) == compute_verdict(facts)
    assert compute_verdict(as_integration).evidence_tier is expected


def test_the_same_facts_give_equal_verdicts() -> None:
    facts = VerdictFacts(
        kind=TestTier.UNIT_TEST,
        planned_estimate=LIGHT,
        flags=("narrow",),
        protected_paths=("a",),
    )

    assert compute_verdict(facts) == compute_verdict(facts)
