"""A plan that makes a unit wait on a less urgent unit that has not started is refused unless it
gives a reason (spec: planner-priority-edges)."""

from __future__ import annotations

import json
import re

import pytest

from agent_build_kit.pipeline.joins import JoinContext
from agent_build_kit.pipeline.planner import PlannerError, parse_plan
from agent_build_kit.pipeline.units import (
    CLOSED,
    FAILED,
    MERGED,
    SATISFIED,
    UnitState,
)
from tests.factories import groups_at, stored_unit


def unit_of(uid: str, group: int, *depends: str, excuse: dict | None = None) -> dict:
    body = {
        "id": uid,
        "change": uid.split("/")[0],
        "title": "A unit",
        "repo": "app",
        "tier": "unit-test",
        "depends_on": list(depends),
        "estimated_lines": 80,
        "groups": [group],
    }
    return body | ({"needs_less_urgent": excuse} if excuse else {})


def reply(*units: dict) -> str:
    return json.dumps({"units": list(units)})


def in_one_change(excuse: dict | None = None) -> str:
    return reply(unit_of("app/1", 1), unit_of("app/2", 2, "app/1", excuse=excuse))


def parse(output: str, priorities: tuple[int, ...] = (3, 1), **kwargs):
    return parse_plan(output, groups=groups_at(*priorities), **kwargs)


def refusal(output: str, priorities: tuple[int, ...] = (3, 1), **kwargs) -> str:
    with pytest.raises(PlannerError) as refused:
        parse(output, priorities, **kwargs)
    return str(refused.value)


def test_a_dependency_on_a_less_urgent_unit_is_refused_naming_both_and_the_ways_out() -> None:
    message = refusal(in_one_change())

    first = message.splitlines()[0]
    assert "app/2" in first and "app/1" in first
    assert re.search(r"priority 1\b", first) and re.search(r"priority 3\b", first)
    assert "needs_less_urgent" in message
    assert "drop" in message.lower()


def test_a_reason_for_the_edge_excuses_it() -> None:
    assert "app/2" in refusal(in_one_change())

    plan = parse(in_one_change({"app/1": "it adds the helper this one calls"}))

    assert [u.id for u in plan.units] == ["app/1", "app/2"]


@pytest.mark.parametrize("priorities", [(1, 1), (1, 3), (2, 2)])
def test_an_equal_or_more_urgent_target_is_left_alone(priorities: tuple[int, int]) -> None:
    # The same plan with the target made less urgent is the one that is refused.
    assert "app/2" in refusal(in_one_change())

    assert parse(in_one_change(), priorities).units


def test_two_refused_edges_are_both_named_with_the_first_on_the_first_line() -> None:
    output = reply(
        unit_of("app/1", 1),
        unit_of("app/2", 2),
        unit_of("app/3", 3, "app/1"),
        unit_of("app/4", 4, "app/2"),
    )

    message = refusal(output, (3, 4, 1, 1))

    first = message.splitlines()[0]
    assert "app/3" in first and "app/1" in first
    assert first.endswith("(and 1 more)")
    assert "app/4" in message and "app/2" in message


def test_a_single_refused_edge_carries_no_count() -> None:
    assert "more)" not in refusal(in_one_change())


def test_the_override_is_keyed_by_the_change_being_planned() -> None:
    target = stored_unit("other/1", change="other", groups=(1,), priority=3)
    context = JoinContext(stored=(target,), catalog={"other": tuple(groups_at(5))})
    stray = unit_of("app/2", 2) | {"change": "other"}
    output = reply(unit_of("app/1", 1, "other/1"), stray)

    with pytest.raises(PlannerError) as refused:
        parse(output, (1, 1), known={"other/1"}, context=context, change="app")

    assert "other/1 (priority 5)" in str(refused.value)


def stored_target(state: UnitState | None, *, priority: int = 3) -> JoinContext:
    target = stored_unit("base/1", change="base", groups=(1,), priority=priority)
    context = JoinContext(stored=(target,), catalog={"base": tuple(groups_at(3))})
    if state is None:
        return context
    started = target.model_copy(update={"state": state, "branch": "spec/base/1"})
    return JoinContext(stored=(started,), catalog=context.catalog)


def against_stored(context: JoinContext) -> str | None:
    output = reply(unit_of("app/1", 1, "base/1"))
    try:
        parse(output, (1,), known={"base/1"}, context=context)
    except PlannerError as error:
        return str(error)
    return None


def test_a_dependency_on_a_stored_unstarted_unit_is_judged_by_its_groups() -> None:
    message = against_stored(stored_target(None, priority=1))

    assert message is not None
    assert "base/1" in message


@pytest.mark.parametrize("state", [FAILED, MERGED, CLOSED, SATISFIED])
def test_a_dependency_on_a_started_or_finished_stored_unit_is_never_refused(
    state: UnitState,
) -> None:
    assert against_stored(stored_target(None)) is not None

    assert against_stored(stored_target(state)) is None


def test_a_plan_unit_that_is_stored_as_started_is_not_refused() -> None:
    started = stored_unit("app/1", change="app", groups=(1,)).model_copy(
        update={"state": FAILED, "branch": "spec/app/1"}
    )
    context = JoinContext(stored=(started,), catalog={"app": tuple(groups_at(3, 1))})
    assert "app/2" in refusal(in_one_change())

    assert parse(in_one_change(), context=context).units


def test_a_unit_whose_groups_are_not_in_the_catalog_counts_as_normal() -> None:
    target = stored_unit("other/1", change="other", groups=(1,), priority=1)
    context = JoinContext(stored=(target,), catalog={})
    output = reply(unit_of("app/1", 1, "other/1"))

    # A priority-2 dependent is more urgent than the normal 3 the unit counts as.
    with pytest.raises(PlannerError) as refused:
        parse(output, (2,), known={"other/1"}, context=context)

    assert "other/1" in str(refused.value)


def test_with_no_context_only_the_plans_own_units_are_compared() -> None:
    output = reply(
        unit_of("app/1", 1),
        unit_of("app/2", 2, "app/1", "base/1", excuse={"app/1": "it adds the helper"}),
    )
    assert "app/2" in refusal(in_one_change())

    assert parse(output, known={"base/1"}).units
