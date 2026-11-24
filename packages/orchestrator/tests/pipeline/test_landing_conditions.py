"""The landing decision names the first condition a unit does not meet (spec: auto-land, only
pipeline code lands a unit, and only when every condition holds)."""

from __future__ import annotations

from typing import Any

import pytest

from agent_build_kit.pipeline.landing_decision import Condition, LandingDecision, decide_landing
from agent_build_kit.pipeline.pr_poller import HOLD_LABEL
from agent_build_kit.pipeline.verdict import ReviewTier
from tests.landing_support import facts

MISSING_ONE: list[tuple[Condition, dict[str, Any]]] = [
    (Condition.NOT_IN_REVIEW, {"state": "running"}),
    (Condition.FEEDBACK_PENDING, {"feedback_pending": True}),
    (Condition.HELD, {"held": True}),
    (Condition.TIER_NOT_AUTO, {"verdict_tier": ReviewTier.LIGHT}),
    (Condition.TIER_NOT_AUTO, {"verdict_tier": ReviewTier.FULL}),
    (Condition.CLASS_NOT_LISTED, {"unit_class": "code"}),
    (Condition.CLASS_NOT_LISTED, {"unit_class": None}),
    (Condition.CLASS_DEMOTED, {"demoted_classes": ("docs",)}),
    (Condition.FORGE_DOES_NOT_MERGE, {"forge_merges": False}),
    (Condition.PULL_REQUEST_CLOSED, {"pr_open": False}),
    (Condition.DRAFT, {"draft": True}),
    (Condition.CONFLICT, {"conflicting": True}),
    (Condition.HOLD_LABEL, {"labels": ("docs", HOLD_LABEL)}),
    (Condition.CHANGES_REQUESTED, {"changes_requested": True}),
    (Condition.HEAD_MOVED, {"head": "b" * 40}),
    (Condition.HEAD_MOVED, {"approved_head": None}),
    (Condition.PARENT_UNMERGED, {"unmerged_parents": ("feature/1",)}),
]


def decide(**changes: Any) -> LandingDecision:
    return decide_landing(facts(**changes))


def test_a_unit_with_every_condition_holding_may_land() -> None:
    decision = decide()
    assert decision.may_land
    assert decision.condition is None


@pytest.mark.parametrize(("condition", "change"), MISSING_ONE)
def test_a_unit_missing_one_condition_is_declined_naming_it(
    condition: Condition, change: dict[str, Any]
) -> None:
    decision = decide(**change)
    assert not decision.may_land
    assert decision.condition is condition


@pytest.mark.parametrize(("condition", "change"), MISSING_ONE)
def test_the_reason_is_words_a_person_can_read(
    condition: Condition, change: dict[str, Any]
) -> None:
    reason = decide(**change).reason
    assert len(reason.split()) >= 3
    assert "_" not in reason
    assert reason == reason.strip()


def test_a_unit_that_lands_has_no_reason_to_give() -> None:
    assert decide().reason == ""


def test_an_empty_list_declines_every_unit() -> None:
    decision = decide(listed_classes=())
    assert not decision.may_land
    assert decision.condition is Condition.CLASS_NOT_LISTED


def test_the_reason_for_an_unmerged_parent_names_the_parent() -> None:
    assert "feature/1" in decide(unmerged_parents=("feature/1",)).reason


def test_the_reason_for_a_class_names_the_class() -> None:
    assert "code" in decide(unit_class="code").reason


def test_the_same_facts_give_the_same_answer() -> None:
    assert decide(draft=True) == decide(draft=True)
