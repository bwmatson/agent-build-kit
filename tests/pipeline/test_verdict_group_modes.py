"""The red-first fact applies to a unit only when a group of it is `tests_and_code`; for a unit
of `tests_only`, `no_code` and `refactor` groups the group modes say it does not apply, it forces
no review tier and the pull request text does not claim the tests came first (spec:
group-build-modes)."""

from __future__ import annotations

from agent_build_kit.model import TestTier
from agent_build_kit.pipeline.pr_body import verified_list
from agent_build_kit.pipeline.verdict import (
    ClassHistory,
    GateResult,
    ReviewTier,
    VerdictFacts,
    compute_verdict,
)
from tests.stub_gate_support import modes
from tests.verdict_support import green_facts

PROVEN = ClassHistory(samples=20, clean=20)


def test_a_unit_of_no_code_groups_has_no_red_first_floor() -> None:
    verdict = compute_verdict(green_facts(group_modes=modes("no_code")), PROVEN)

    assert verdict.tier is ReviewTier.AUTO
    assert "red-first" not in verdict.reason


def test_a_missing_red_first_is_not_a_floor_for_tests_only_no_code_and_refactor_groups() -> None:
    verdict = compute_verdict(
        green_facts(
            red_first=GateResult.MISSING,
            group_modes=modes("tests_only", "no_code", "refactor"),
        ),
        PROVEN,
    )

    assert verdict.tier is ReviewTier.AUTO


def test_the_text_of_a_unit_of_no_code_groups_does_not_say_the_tests_came_first() -> None:
    text = verified_list(
        VerdictFacts(
            kind=TestTier.UNIT_TEST,
            red_first=GateResult.PASSED,
            unit_test=GateResult.PASSED,
            group_modes=modes("no_code", "tests_only"),
        ),
        rounds=1,
    )

    assert "seen to fail" not in text
    assert "committed first" not in text
    assert "not recorded" not in text


def test_the_text_of_a_refactor_says_it_was_a_reorganization_and_no_test_was_added() -> None:
    text = verified_list(
        VerdictFacts(
            kind=TestTier.UNIT_TEST,
            red_first=GateResult.PASSED,
            unit_test=GateResult.PASSED,
            group_modes=modes("refactor"),
        ),
        rounds=1,
    ).lower()

    assert "reorganization" in text
    assert "no test was added" in text
    assert "seen to fail" not in text
