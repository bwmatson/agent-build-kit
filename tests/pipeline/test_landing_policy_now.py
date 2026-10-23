"""The policy is read as it stands now, not as it stood at approval (spec: auto-land, only
pipeline code lands a unit, and only when every condition holds)."""

from __future__ import annotations

from agent_build_kit.pipeline.landing_decision import Condition, decide_landing
from tests.landing_support import facts


def test_a_unit_approved_while_its_class_was_listed_is_declined_once_it_is_removed() -> None:
    unit = facts(listed_classes=("docs",))
    assert decide_landing(unit).may_land
    decision = decide_landing(unit.model_copy(update={"listed_classes": ()}))
    assert not decision.may_land
    assert decision.condition is Condition.CLASS_NOT_LISTED


def test_a_class_listed_after_approval_lands_the_unit_on_the_next_pass() -> None:
    unit = facts(listed_classes=())
    assert not decide_landing(unit).may_land
    assert decide_landing(unit.model_copy(update={"listed_classes": ("docs",)})).may_land


def test_a_unit_with_no_recorded_verdict_is_declined_as_having_none() -> None:
    decision = decide_landing(facts(verdict_tier=None))
    assert not decision.may_land
    assert decision.condition is Condition.NO_VERDICT
    assert "verdict" in decision.reason
