"""A split plan is the held unit's groups in order as contiguous runs, with the parent's id and
`-s<k>`, chained from what the held unit waited on and on nothing else (spec: split-planning)."""

from __future__ import annotations

import pytest

from agent_build_kit.pipeline.planner import PlannerError
from tests.split_plan_support import PIECES, correct, piece, split_plan, use_per_tier_sizing


@pytest.fixture(autouse=True)
def per_tier_sizing() -> None:
    use_per_tier_sizing()


FIRST, SECOND, THIRD = PIECES


def test_the_correct_split_around_a_driver_is_accepted_and_out_of_order_is_refused() -> None:
    plan = split_plan(*correct())
    assert [unit.groups for unit in plan.units] == [(1, 2), (3,), (4, 5)]
    assert [unit.review_tier for unit in plan.units] == ["auto", "full", "auto"]

    with pytest.raises(PlannerError, match="order"):
        split_plan(
            piece(FIRST, [1, 2], "auto", 300, after=("c/0",)),
            piece(SECOND, [4, 5], "auto", 300, after=(FIRST,)),
            piece(THIRD, [3], "full", 300, after=(SECOND,)),
        )


def test_pieces_that_interleave_the_groups_are_refused_as_not_contiguous_runs() -> None:
    with pytest.raises(PlannerError, match="contiguous"):
        split_plan(
            piece(FIRST, [1, 3], "full", 300, after=("c/0",)),
            piece(SECOND, [2, 4, 5], "full", 300, after=(FIRST,)),
            drivers=(),
        )


@pytest.mark.parametrize(
    "labels",
    [("a", "b", "c"), ("c/1-s2", "c/1-s3", "c/1-s4"), ("c/9-s1", "c/9-s2", "c/9-s3")],
    ids=["free labels", "numbered from 2", "another parent"],
)
def test_ids_other_than_the_parents_with_the_place_are_refused(labels: tuple[str, ...]) -> None:
    first, second, third = labels
    with pytest.raises(PlannerError) as refused:
        split_plan(
            piece(first, [1, 2], "auto", 300, after=("c/0",)),
            piece(second, [3], "full", 300, after=(first,)),
            piece(third, [4, 5], "auto", 300, after=(second,)),
        )

    assert FIRST in str(refused.value)


def test_a_first_piece_that_does_not_depend_on_what_the_held_unit_depended_on_is_refused() -> None:
    with pytest.raises(PlannerError) as refused:
        split_plan(
            piece(FIRST, [1, 2], "auto", 300, after=()),
            piece(SECOND, [3], "full", 300, after=(FIRST,)),
            piece(THIRD, [4, 5], "auto", 300, after=(SECOND,)),
        )

    text = str(refused.value)
    assert FIRST in text and "c/0" in text, text


def test_a_later_piece_that_does_not_depend_on_the_one_before_is_refused() -> None:
    with pytest.raises(PlannerError) as refused:
        split_plan(
            piece(FIRST, [1, 2], "auto", 300, after=("c/0",)),
            piece(SECOND, [3], "full", 300, after=(FIRST,)),
            piece(THIRD, [4, 5], "auto", 300, after=(FIRST,)),
        )

    text = str(refused.value)
    assert THIRD in text and SECOND in text, text


def test_a_piece_depending_on_another_unit_of_the_change_is_refused() -> None:
    with pytest.raises(PlannerError) as refused:
        split_plan(
            piece(FIRST, [1, 2], "auto", 300, after=("c/0",)),
            piece(SECOND, [3], "full", 300, after=(FIRST,)),
            piece(THIRD, [4, 5], "auto", 300, after=(SECOND, "c/9")),
            known={"c/0", "c/9"},
        )

    text = str(refused.value)
    assert THIRD in text and "c/9" in text, text
