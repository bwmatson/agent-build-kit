"""The plan's validation of an acceptance or narrow unit is as it was: it must reach every unit
it exercises, through others, and a narrowing unit must reach every independent unit."""

from __future__ import annotations

import pytest

from agent_build_kit.pipeline.planner import PlannerError, check_flagged_groups
from agent_build_kit.pipeline.units import Unit, plan_units
from agent_build_kit.pipeline.work_graph import TaskGroup
from tests.factories import groups_at, unit


def groups(*flags: str, independent: tuple[int, ...] = ()) -> list[TaskGroup]:
    return [
        group.model_copy(update={"flag": flags[n], "independent": n + 1 in independent})
        for n, group in enumerate(groups_at(*[3] * len(flags)))
    ]


def chain(*depends: tuple[str, ...]) -> list[Unit]:
    return [
        unit(f"feature/{n}", change="feature", groups=(n,), depends_on=on)
        for n, on in enumerate(depends, start=1)
    ]


def test_an_acceptance_unit_reaching_every_exercised_unit_through_others_passes() -> None:
    units = chain((), ("feature/1",), ("feature/2",), ("feature/3",))

    check_flagged_groups(units, groups("", "", "", "acceptance"))


def test_an_acceptance_unit_that_misses_a_unit_is_refused_naming_it() -> None:
    units = chain((), ("feature/1",), (), ("feature/2",))

    with pytest.raises(
        PlannerError, match=r"acceptance unit feature/4 does not wait for feature/3"
    ):
        check_flagged_groups(units, groups("", "", "", "acceptance"))


def test_a_narrowing_unit_that_does_not_reach_an_independent_unit_is_refused() -> None:
    units = chain((), ("feature/1",), (), ("feature/2",))

    with pytest.raises(PlannerError, match=r"narrowing unit feature/4 does not wait for feature/3"):
        check_flagged_groups(units, groups("", "", "", "narrow", independent=(3,)))


def test_the_units_plan_units_gives_pass_the_validation() -> None:
    checked = groups("", "", "acceptance", "narrow", independent=(2,))
    rows = [
        {
            "number": g.number,
            "repo": g.repo,
            "tier": g.tier,
            "title": g.title,
            "estimated_lines": 200,
            "flag": g.flag,
            "independent": g.independent,
        }
        for g in checked
    ]

    check_flagged_groups(plan_units("feature", rows, min_lines=100, max_lines=1000), checked)
