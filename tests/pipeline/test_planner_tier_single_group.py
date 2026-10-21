"""A single group over its unit's tier ceiling is reported as needing its tasks split, before
any combined unit is (spec: unit-sizing)."""

from __future__ import annotations

import pytest

from agent_build_kit.pipeline.planner import GroupTooLarge, parse_plan
from tests.tier_ceiling_support import GROUPS, configure, graph


@pytest.fixture(autouse=True)
def per_tier_sizing() -> None:
    configure(enabled=True)


def test_a_single_group_over_its_tiers_ceiling_names_the_group_the_tier_and_the_split() -> None:
    output = graph({"id": "c/1", "groups": [1], "estimated_lines": 5200, "review_tier": "auto"})

    with pytest.raises(GroupTooLarge) as refused:
        parse_plan(output, groups=GROUPS[:1])

    message = str(refused.value)
    assert "group 1" in message
    assert "auto" in message
    assert "5000" in message
    assert "split" in message


def test_it_is_reported_before_a_combined_unit_over_its_ceiling() -> None:
    output = graph(
        {"id": "c/1", "groups": [2, 3], "estimated_lines": 2600, "review_tier": "light"},
        {"id": "c/2", "groups": [1], "estimated_lines": 5200, "review_tier": "auto"},
    )

    with pytest.raises(GroupTooLarge) as refused:
        parse_plan(output, groups=GROUPS)

    assert "group 1" in str(refused.value)
