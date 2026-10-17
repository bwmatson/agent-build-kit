"""The ceiling in the planner's own terms, and the recent units that back a ratio.

Both are pure functions of the ceiling and the stored units, so these tests need no planner.
"""

from __future__ import annotations

import random

import pytest

from agent_build_kit.pipeline.unit_size import Kind, largest_raw, recent_examples
from agent_build_kit.pipeline.units import IN_REVIEW
from tests.calibration_support import sample

APP = Kind(repo="app", tier="unit-test")


@pytest.mark.parametrize(
    ("limit", "ratio", "expected"),
    [(750, 1.5, 500), (750, 1.0, 750), (750, 1.51, 496), (400, 1.51, 264), (400, 1.5, 266)],
)
def test_the_largest_raw_estimate_is_the_limit_over_the_ratio_rounded_down(
    limit: int, ratio: float, expected: int
) -> None:
    assert largest_raw(limit, ratio) == expected


def test_the_most_recent_merged_units_are_the_examples_newest_first() -> None:
    units = [sample(1.5, at=at, uid=f"u{at}/1") for at in (3, 1, 6, 2, 5, 4)]

    shown = recent_examples(units, APP, 3)

    assert [u.id for u in shown] == ["u6/1", "u5/1", "u4/1"]


def test_units_that_merged_at_the_same_moment_are_ordered_by_id() -> None:
    units = [sample(1.5, at=7, uid=uid) for uid in ("c/1", "a/1", "b/1")]
    older = sample(1.5, at=1, uid="z/1")

    shown = recent_examples([*units, older], APP, 4)

    assert [u.id for u in shown] == ["a/1", "b/1", "c/1", "z/1"]


def test_the_same_units_give_the_same_examples_whatever_order_they_are_held_in() -> None:
    units = [sample(1.5, at=at // 2, uid=f"u{at}/1") for at in range(12)]
    expected = [u.id for u in recent_examples(units, APP, 5)]

    for seed in range(5):
        shuffled = random.Random(seed).sample(units, len(units))
        assert [u.id for u in recent_examples(shuffled, APP, 5)] == expected
    assert len(expected) == 5


def test_a_unit_with_nothing_to_compare_or_not_merged_is_not_an_example() -> None:
    units = [
        sample(1.5, at=9, uid="no-estimate/1", estimate=0, actual=300),
        sample(1.5, at=8, uid="no-size/1").model_copy(update={"actual_lines": None}),
        sample(1.5, at=7, uid="running/1", state=IN_REVIEW),
        sample(1.5, at=1, uid="counted/1"),
    ]

    assert [u.id for u in recent_examples(units, APP, 3)] == ["counted/1"]


def test_only_units_of_the_kind_are_examples() -> None:
    units = [
        sample(1.5, at=5, uid="other-tier/1", tier="e2e-test"),
        sample(1.5, at=4, uid="other-repo/1", repo="platform"),
        sample(1.5, at=3, uid="flagged/1", flag="contract"),
        sample(1.5, at=1, uid="mine/1"),
    ]

    assert [u.id for u in recent_examples(units, APP, 3)] == ["mine/1"]


def test_no_examples_are_asked_for_when_the_number_is_zero() -> None:
    assert recent_examples([sample(1.5, at=1)], APP, 0) == []
