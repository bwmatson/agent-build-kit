"""The landing decision reads the pull request's checks as evidence (spec: auto-land, the
pipeline reads the checks itself, and no checks is no evidence)."""

from __future__ import annotations

import pytest

from agent_build_kit.forges.base import CheckStatus
from agent_build_kit.pipeline.landing_decision import Condition, decide_landing
from tests.landing_support import check, facts

THREE = ("build", "lint", "test")


def test_three_passed_checks_may_land_and_one_failed_does_not() -> None:
    passed = decide_landing(facts(checks=tuple(check(n) for n in THREE)))
    failed = decide_landing(
        facts(checks=(check("build"), check("lint", CheckStatus.FAILED), check("test")))
    )
    assert passed.may_land
    assert not failed.may_land
    assert failed.condition is Condition.CHECKS_FAILED


def test_a_failed_check_is_a_different_answer_from_waiting() -> None:
    failed = decide_landing(facts(checks=(check("build", CheckStatus.FAILED),)))
    pending = decide_landing(facts(checks=(check("build", CheckStatus.PENDING),)))
    assert failed.condition is Condition.CHECKS_FAILED
    assert pending.condition is Condition.CHECKS_PENDING


@pytest.mark.parametrize("status", [CheckStatus.PENDING, CheckStatus.CANCELLED])
def test_a_pending_or_cancelled_check_waits_and_is_not_declined_for_good(
    status: CheckStatus,
) -> None:
    decision = decide_landing(facts(checks=(check("build"), check("test", status))))
    assert not decision.may_land
    assert decision.condition is Condition.CHECKS_PENDING
    assert decision.condition not in (Condition.NO_CHECKS, Condition.CHECKS_FAILED)


def test_a_failed_check_wins_over_a_pending_one() -> None:
    decision = decide_landing(
        facts(checks=(check("a", CheckStatus.PENDING), check("b", CheckStatus.FAILED)))
    )
    assert decision.condition is Condition.CHECKS_FAILED


def test_no_check_registered_is_declined_for_want_of_evidence() -> None:
    decision = decide_landing(facts(checks=()))
    assert not decision.may_land
    assert decision.condition is Condition.NO_CHECKS
    assert "evidence" in decision.reason


def test_the_answer_does_not_depend_on_the_name_of_a_check() -> None:
    named = ("required", "ci/required-check", "x")
    assert decide_landing(facts(checks=tuple(check(n) for n in named))).may_land
    assert decide_landing(facts(checks=tuple(check(n) for n in THREE))).may_land
    assert (
        decide_landing(facts(checks=(check("required", CheckStatus.FAILED),))).condition
        is Condition.CHECKS_FAILED
    )
    assert decide_landing(facts(checks=(check("optional", CheckStatus.FAILED),))).condition is (
        Condition.CHECKS_FAILED
    )
