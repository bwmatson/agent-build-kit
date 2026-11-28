"""The verdict's floors from the plan alone (spec: review-verdict, deterministic verdict)."""

from __future__ import annotations

import pytest

from agent_build_kit.model import TestTier
from agent_build_kit.pipeline.verdict import ClassHistory, ReviewTier, VerdictFacts, compute_verdict
from tests.verdict_support import green_facts

AUTO, LIGHT, FULL = ReviewTier.AUTO, ReviewTier.LIGHT, ReviewTier.FULL

CASES = [
    pytest.param(green_facts(), AUTO, id="no-floor"),
    pytest.param(green_facts(planned_estimate=AUTO), AUTO, id="auto"),
    pytest.param(green_facts(planned_estimate=LIGHT), LIGHT, id="light"),
    pytest.param(green_facts(planned_estimate=FULL), FULL, id="full"),
    pytest.param(
        green_facts(protected_paths=("db/migrations/001.sql",)), FULL, id="protected-path"
    ),
    pytest.param(green_facts(flags=("contract",)), FULL, id="contract"),
    pytest.param(green_facts(flags=("narrow",)), FULL, id="narrow"),
    pytest.param(green_facts(flags=("acceptance",)), FULL, id="acceptance"),
    pytest.param(
        green_facts(planned_estimate=LIGHT, flags=("contract",)), FULL, id="light-and-flag"
    ),
    pytest.param(
        green_facts(planned_estimate=AUTO, protected_paths=("Dockerfile",)),
        FULL,
        id="auto-and-path",
    ),
    pytest.param(
        green_facts(planned_estimate=FULL, protected_paths=("Dockerfile",), flags=("narrow",)),
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


RULE = "pyproject.toml: tool.ruff"


@pytest.mark.parametrize(
    ("settings", "paths", "tier", "reason"),
    [
        pytest.param((RULE,), (), FULL, f"it changed the protected setting {RULE}", id="one-entry"),
        pytest.param(
            (RULE, "package.json: scripts.test"),
            (),
            FULL,
            f"it changed the protected setting {RULE}",
            id="two-entries-name-the-first",
        ),
        pytest.param((), (), AUTO, "", id="none-stays-auto"),
        pytest.param(
            (RULE,),
            ("Dockerfile",),
            FULL,
            "it changed the protected path Dockerfile",
            id="the-protected-path-reason-is-kept",
        ),
    ],
)
def test_a_changed_protected_setting_floors_a_proven_auto_unit_at_full(
    settings: tuple[str, ...], paths: tuple[str, ...], tier: ReviewTier, reason: str
) -> None:
    facts = green_facts(protected_settings=settings, protected_paths=paths)

    verdict = compute_verdict(facts, ClassHistory(samples=20, clean=20))

    assert verdict.tier is tier
    if reason:
        assert verdict.reason == reason


def test_the_same_facts_give_equal_verdicts() -> None:
    facts = green_facts(planned_estimate=LIGHT, flags=("narrow",), protected_paths=("a",))

    assert compute_verdict(facts) == compute_verdict(facts)
