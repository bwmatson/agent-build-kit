"""A unit carries the project of its groups; groups of two projects are never one unit."""

from __future__ import annotations

from agent_build_kit.pipeline.units import branch_name, plan_units
from tests.factories import unit


def group(number: int, project: str = ".", lines: int = 200, **kw) -> dict:
    return {
        "number": number,
        "repo": "app",
        "project": project,
        "tier": "tier1",
        "title": f"group {number}",
        "estimated_lines": lines,
        "fans_out": kw.get("fans_out", False),
        "independent": kw.get("independent", False),
    }


def test_a_root_group_and_a_web_group_of_one_repo_are_two_units() -> None:
    units = plan_units("add-marker", [group(1), group(2, "web")], min_lines=500, max_lines=1000)

    assert [(u.groups, u.project) for u in units] == [((1,), "."), ((2,), "web")]
    assert units[1].depends_on == ("add-marker/1",)
    assert branch_name(units[1]) == branch_name(unit("add-marker/2"))


def test_two_small_web_groups_are_one_unit_of_the_web_project() -> None:
    units = plan_units(
        "add-marker", [group(1, "web"), group(2, "web")], min_lines=500, max_lines=1000
    )

    assert [(u.groups, u.project) for u in units] == [((1, 2), "web")]


def test_a_change_of_project_splits_a_unit_that_was_under_the_floor() -> None:
    units = plan_units(
        "add-marker",
        [group(1, "web", lines=50), group(2, ".", lines=50), group(3, ".", lines=50)],
        min_lines=500,
        max_lines=1000,
    )

    assert [(u.groups, u.project) for u in units] == [((1,), "web"), ((2, 3), ".")]


def test_an_independent_group_and_a_fan_out_point_behave_as_before_in_a_project() -> None:
    units = plan_units(
        "add-marker",
        [
            group(1, "web", fans_out=True),
            group(2, "web"),
            group(3, "web", independent=True),
        ],
        min_lines=500,
        max_lines=1000,
    )

    assert [(u.groups, u.project) for u in units] == [((1,), "web"), ((2,), "web"), ((3,), "web")]
    assert units[1].depends_on == ("add-marker/1",)
    assert units[2].depends_on == ()
