"""A join is judged on the direct dependencies of the units it involves.

A unit that lists a dependency another of its dependencies reaches is judged as if it did
not, in the store and in the plan, so a unit after the one taken in no longer counts as a
second dependent of the unit joined onto for listing it as well.
"""

from __future__ import annotations

import pytest

from agent_build_kit.pipeline.joins import JoinContext, JoinRefused, check_joins
from agent_build_kit.pipeline.units import MERGED, Join, Unit
from agent_build_kit.pipeline.work_graph import TaskGroup
from tests.factories import ordinary_floor, stored_unit
from tests.factories import unit as planned


def stored(uid: str, **overrides):
    """A stored unit of `feature`, whose groups `CATALOG` knows."""
    return stored_unit(uid, change="feature", **overrides)


CATALOG = {
    "feature": tuple(
        TaskGroup(number=n, repo="app", tier="unit-test", title="A group", line=3, task_count=2)
        for n in range(1, 8)
    )
}


def check(*joins: Join, units: list, plan: list[Unit] | None = None) -> None:
    check_joins(
        list(joins),
        context=JoinContext(stored=tuple(units), catalog=CATALOG),
        plan=plan or [],
        change="plan" if plan else None,
        groups=[],
        built=set(),
        floor=ordinary_floor,
    )


def line_with_redundant_third() -> list:
    """A, B after A, and C after B that also lists A, which B reaches."""
    return [
        stored("feature/1"),
        stored("feature/2", depends_on=("feature/1",)),
        stored("feature/3", depends_on=("feature/2", "feature/1")),
    ]


def test_a_unit_after_the_one_taken_in_that_also_lists_the_unit_joined_onto_permits_it() -> None:
    check(Join(onto="feature/1", unit="feature/2"), units=line_with_redundant_third())


def test_a_unit_that_does_not_depend_on_the_taken_one_still_refuses_and_is_the_one_named() -> None:
    units = [*line_with_redundant_third(), stored("feature/4", depends_on=("feature/1",))]

    with pytest.raises(JoinRefused) as refused:
        check(Join(onto="feature/1", unit="feature/2"), units=units)

    assert "feature/4" in str(refused.value)
    assert "feature/3" not in str(refused.value)


def test_a_taken_unit_waiting_on_another_unfinished_unit_still_refuses() -> None:
    units = line_with_redundant_third()
    check(Join(onto="feature/1", unit="feature/2"), units=units)
    units[1] = stored("feature/2", depends_on=("feature/1", "feature/5"))
    units.append(stored("feature/5"))

    with pytest.raises(JoinRefused, match="feature/5.*unfinished"):
        check(Join(onto="feature/1", unit="feature/2"), units=units)


def test_a_taken_unit_waiting_on_a_merged_unit_is_not_held_by_it() -> None:
    units = line_with_redundant_third()
    units[1] = stored("feature/2", depends_on=("feature/5", "feature/1"))
    units.append(stored("feature/5", state=MERGED))

    check(Join(onto="feature/1", unit="feature/2"), units=units)


def test_a_unit_that_does_not_depend_on_the_unit_joined_onto_directly_is_not_a_line() -> None:
    units = line_with_redundant_third()
    check(Join(onto="feature/1", unit="feature/2"), units=units)

    with pytest.raises(JoinRefused, match="does not depend on feature/1"):
        check(Join(onto="feature/1", unit="feature/3"), units=units)


def test_a_planned_unit_listing_the_taken_unit_and_the_joined_one_permits_the_join() -> None:
    units = [stored("feature/1"), stored("feature/2", depends_on=("feature/1",))]
    plan = [planned("plan/1", change="plan", depends_on=("feature/2", "feature/1"))]

    check(Join(onto="feature/1", unit="feature/2"), units=units, plan=plan)


def test_a_planned_unit_after_the_taken_one_is_repointed_for_a_later_join() -> None:
    units = [
        stored("feature/1"),
        stored("feature/2", depends_on=("feature/1",)),
        stored("feature/3", depends_on=("feature/2",)),
    ]
    plan = [planned("plan/1", change="plan", depends_on=("feature/2",))]

    with pytest.raises(JoinRefused, match="plan/1 already depends on feature/1"):
        check(
            Join(onto="feature/1", unit="feature/2"),
            Join(onto="feature/1", unit="feature/3"),
            units=units,
            plan=plan,
        )


def test_the_plans_redundant_dependencies_are_reduced_for_a_later_join() -> None:
    units = [
        stored("feature/1"),
        stored("feature/2", depends_on=("feature/1",)),
        stored("feature/3", depends_on=("feature/2",)),
    ]
    plan = [planned("plan/1", change="plan", depends_on=("feature/2", "feature/1"))]

    check(Join(onto="feature/1", unit="feature/2"), units=units, plan=plan)
    with pytest.raises(JoinRefused, match="plan/1 already depends on feature/1"):
        check(
            Join(onto="feature/1", unit="feature/2"),
            Join(onto="feature/1", unit="feature/3"),
            units=units,
            plan=plan,
        )
