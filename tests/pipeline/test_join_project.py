"""A join never crosses projects, and the planner is shown each unit's project."""

from __future__ import annotations

import pytest

from agent_build_kit.pipeline.joins import JoinContext, JoinRefused, check_joins
from agent_build_kit.pipeline.planner import in_flight_item
from agent_build_kit.pipeline.units import Join
from agent_build_kit.pipeline.work_graph import TaskGroup
from tests.factories import ordinary_floor, stored_unit


def tagged(project: str) -> TaskGroup:
    return TaskGroup(
        number=1,
        repo="app",
        project=project,
        tier="unit-test",
        title="A group",
        line=3,
        task_count=2,
    )


def check(join: Join, *stored, catalog: dict, change: str | None = None, groups=()) -> None:
    check_joins(
        [join],
        context=JoinContext(stored=tuple(stored), catalog=catalog),
        plan=[],
        change=change,
        groups=list(groups),
        built=set(),
        ceiling=750,
        floor=ordinary_floor,
    )


def test_a_unit_join_across_projects_is_refused_and_one_within_a_project_is_not() -> None:
    web = stored_unit("a/1", change="a", project="web")
    later_web = stored_unit("b/1", change="b", project="web", depends_on=("a/1",))
    later_root = stored_unit("b/1", change="b", project=".", depends_on=("a/1",))
    join = Join(onto="a/1", unit="b/1")

    check(join, web, later_web, catalog={"a": (tagged("web"),), "b": (tagged("web"),)})
    with pytest.raises(JoinRefused, match="project"):
        check(join, web, later_root, catalog={"a": (tagged("web"),), "b": (tagged("."),)})


def test_a_group_joined_onto_a_unit_of_another_project_is_refused() -> None:
    root = stored_unit("a/1", change="a", project=".")
    join = Join(onto="a/1", change="feature", groups=(1,), estimated_lines=100)

    with pytest.raises(JoinRefused, match="project"):
        check(join, root, catalog={"a": (tagged("."),)}, change="feature", groups=[tagged("web")])


def test_each_unit_in_flight_carries_its_project() -> None:
    web, root = stored_unit("a/1", project="web"), stored_unit("b/1")
    assert in_flight_item(web, [web, root])["project"] == "web"
    assert in_flight_item(root, [web, root])["project"] == "."
