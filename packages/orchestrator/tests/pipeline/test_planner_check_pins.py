"""A split plan that ignores the pins is refused naming the unit and the rule (spec:
split-planning)."""

from __future__ import annotations

import pytest

from agent_build_kit.pipeline.planner import PlannerError
from tests.split_plan_support import PIECES, piece, split_plan, use_per_tier_sizing


@pytest.fixture(autouse=True)
def per_tier_sizing() -> None:
    use_per_tier_sizing()


FIRST, SECOND, THIRD = PIECES


def test_a_driver_group_beside_another_group_is_refused_naming_the_unit_and_both_groups() -> None:
    with pytest.raises(PlannerError) as refused:
        split_plan(
            piece(FIRST, [1, 2], "auto", 300, after=("c/0",)),
            piece(SECOND, [3, 4], "full", 300, after=(FIRST,)),
            piece(THIRD, [5], "auto", 300, after=(SECOND,)),
        )

    text = str(refused.value)
    assert SECOND in text and "group 3" in text and "group 4" in text, text


def test_a_driver_unit_at_the_planned_tier_is_refused_naming_the_earned_tier() -> None:
    with pytest.raises(PlannerError) as refused:
        split_plan(
            piece(FIRST, [1, 2], "auto", 300, after=("c/0",)),
            piece(SECOND, [3], "auto", 300, after=(FIRST,)),
            piece(THIRD, [4, 5], "auto", 300, after=(SECOND,)),
        )

    text = str(refused.value)
    assert SECOND in text and "full" in text, text


def test_a_unit_of_other_groups_at_the_earned_tier_is_refused() -> None:
    with pytest.raises(PlannerError) as refused:
        split_plan(
            piece(FIRST, [1, 2], "full", 300, after=("c/0",)),
            piece(SECOND, [3], "full", 300, after=(FIRST,)),
            piece(THIRD, [4, 5], "auto", 300, after=(SECOND,)),
        )

    text = str(refused.value)
    assert FIRST in text and "auto" in text, text


def test_adjacent_drivers_share_a_unit_and_drivers_with_a_group_between_them_do_not() -> None:
    plan = split_plan(
        piece(FIRST, [1], "auto", 300, after=("c/0",)),
        piece(SECOND, [2, 3], "full", 600, after=(FIRST,)),
        piece(THIRD, [4, 5], "auto", 300, after=(SECOND,)),
        drivers=(2, 3),
    )
    assert [unit.groups for unit in plan.units] == [(1,), (2, 3), (4, 5)]

    with pytest.raises(PlannerError) as refused:
        split_plan(
            piece(FIRST, [1], "auto", 300, after=("c/0",)),
            piece(SECOND, [2, 3, 4], "full", 600, after=(FIRST,)),
            piece(THIRD, [5], "auto", 300, after=(SECOND,)),
            drivers=(2, 4),
        )
    text = str(refused.value)
    assert SECOND in text and "group 3" in text, text


def test_with_no_drivers_every_unit_must_be_at_the_earned_tier() -> None:
    plan = split_plan(
        piece(FIRST, [1, 2, 3], "full", 600, after=("c/0",)),
        piece(SECOND, [4, 5], "full", 300, after=(FIRST,)),
        drivers=(),
    )
    assert [unit.review_tier for unit in plan.units] == ["full", "full"]

    with pytest.raises(PlannerError) as refused:
        split_plan(
            piece(FIRST, [1, 2, 3], "full", 600, after=("c/0",)),
            piece(SECOND, [4, 5], "auto", 300, after=(FIRST,)),
            drivers=(),
        )
    text = str(refused.value)
    assert SECOND in text and "full" in text, text
