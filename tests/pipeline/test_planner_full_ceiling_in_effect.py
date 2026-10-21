"""With per-tier sizing off and only `review.ceilings.full` set, the one ceiling every part of
the planner reads is that `full` ceiling: the instructions, the calibration figures, the plan
check and the join check (spec: review-tier-ceilings)."""

from __future__ import annotations

import json

import pytest

from agent_build_kit.pipeline.joins import JoinContext
from agent_build_kit.pipeline.planner import PlannerError, parse_plan
from agent_build_kit.pipeline.unit_size import largest_raw
from tests.calibration_support import limits
from tests.factories import activate_with, stored_unit
from tests.tier_ceiling_support import GROUPS, graph
from tests.tier_prompt_support import landed_at_one_and_a_half, prompt_for, ratio_of


@pytest.fixture(autouse=True)
def only_the_full_ceiling_set() -> None:
    limits()
    activate_with(review={"enabled": False, "ceilings": {"full": 600}})


def test_the_instructions_state_the_full_ceiling() -> None:
    prompt = prompt_for([])

    assert "estimated over 600 changed lines" in prompt
    assert "at or under 600 changed lines" in prompt
    assert "750" not in prompt


def test_the_calibration_figures_are_worked_out_from_the_full_ceiling() -> None:
    units = landed_at_one_and_a_half()
    ratio = ratio_of(units).ratio

    prompt = prompt_for(units)

    assert f"largest raw estimate {largest_raw(600, ratio)}," in prompt
    assert f"(app unit-test: {largest_raw(600, ratio)})" in prompt


def test_the_plan_check_refuses_over_the_full_ceiling() -> None:
    unit = {"id": "c/1", "groups": [1, 2, 3], "estimated_lines": 700}

    with pytest.raises(PlannerError, match="ceiling of 600"):
        parse_plan(graph(unit), groups=GROUPS)


def test_the_join_check_refuses_a_join_over_the_full_ceiling() -> None:
    onto = stored_unit("base/1", change="base", estimated_lines=100, groups=(1,))
    join = {"onto": "base/1", "change": "c", "groups": [1], "estimated_lines": 600}

    with pytest.raises(PlannerError, match="600"):
        parse_plan(
            json.dumps({"units": [], "joins": [join]}),
            groups=GROUPS[:1],
            change="c",
            context=JoinContext(stored=(onto,), catalog={"base": tuple(GROUPS[:1])}),
        )
