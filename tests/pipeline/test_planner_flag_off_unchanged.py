"""With per-tier sizing off, the plan check's messages are as they were: one ceiling for every
tier, and no tier named (spec: unit-sizing).

A repo's `full` ceiling stands in for the ceiling in effect, and a reply's tier is ignored.
"""

from __future__ import annotations

import pytest

from agent_build_kit.pipeline.planner import GroupTooLarge, PlannerError, parse_plan
from tests.tier_ceiling_support import GROUPS, configure, graph


@pytest.fixture(autouse=True)
def flag_off() -> None:
    configure(enabled=False, repo_ceilings={"full": 1000})


def test_a_combined_unit_is_refused_as_before_against_the_ceiling_in_effect() -> None:
    output = graph({"id": "c/1", "groups": [1, 2, 3], "estimated_lines": 1200})

    with pytest.raises(PlannerError) as refused:
        parse_plan(output, groups=GROUPS)

    assert str(refused.value) == (
        "unit c/1 is estimated at 1200 changed lines, over the ceiling of 1000 — "
        "its groups must go in more than one unit"
    )


def test_a_single_group_is_refused_as_before() -> None:
    output = graph({"id": "c/1", "groups": [1], "estimated_lines": 1200})

    with pytest.raises(GroupTooLarge) as refused:
        parse_plan(output, groups=GROUPS[:1])

    assert str(refused.value) == (
        "group 1 of c is estimated at 1200 changed lines, over the ceiling of 1000 — "
        "no unit can hold it, so its tasks must be split in tasks.md"
    )


def test_a_tier_in_the_reply_does_not_loosen_the_ceiling() -> None:
    output = graph(
        {"id": "c/1", "groups": [1, 2, 3], "estimated_lines": 2000, "review_tier": "auto"}
    )

    with pytest.raises(PlannerError, match="ceiling of 1000") as refused:
        parse_plan(output, groups=GROUPS)

    assert "auto" not in str(refused.value)
