"""The planner's units are checked against the project each group is tagged for."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_build_kit.pipeline.planner import PlannerError, parse_plan, plan_kind
from agent_build_kit.pipeline.unit_size import Kind
from agent_build_kit.pipeline.work_graph import TaskGroup
from tests.project_workspace import app_with_projects


def tagged(number: int, project: str = ".") -> TaskGroup:
    return TaskGroup(
        number=number,
        repo="app",
        project=project,
        tier="unit-test",
        title=f"Group {number}",
        line=3 * number,
        task_count=2,
    )


def reply(**unit: object) -> str:
    body = {
        "id": "c/1",
        "change": "c",
        "title": "A unit",
        "repo": "app",
        "tier": "unit-test",
        **unit,
    }
    return json.dumps({"units": [body]})


@pytest.fixture(autouse=True)
def declaring_web(tmp_path: Path) -> None:
    app_with_projects(tmp_path / "planning", "web")


def test_a_unit_given_a_group_of_another_project_is_refused_naming_both() -> None:
    with pytest.raises(PlannerError) as refused:
        parse_plan(reply(groups=[1], project="."), groups=[tagged(1, "web")])

    message = str(refused.value)
    assert "c/1" in message
    assert "group 1" in message
    assert "web" in message
    assert "." in message.replace("c/1", "")


def test_a_project_the_repo_does_not_declare_is_refused_naming_the_unit_and_project() -> None:
    with pytest.raises(PlannerError) as refused:
        parse_plan(reply(groups=[1], project="mobile"), groups=[tagged(1)])

    assert "c/1" in str(refused.value)
    assert "mobile" in str(refused.value)


def test_a_unit_without_a_project_takes_the_project_of_its_groups() -> None:
    output = json.dumps(
        {
            "units": [
                {"id": "c/1", "change": "c", "title": "Root", "repo": "app", "tier": "unit-test"}
                | {"groups": [1]},
                {"id": "c/2", "change": "c", "title": "Web", "repo": "app", "tier": "unit-test"}
                | {"groups": [2, 3], "depends_on": ["c/1"]},
            ]
        }
    )

    plan = parse_plan(output, groups=[tagged(1), tagged(2, "web"), tagged(3, "web")])

    assert [u.project for u in plan.units] == [".", "web"]


def test_the_calibration_kind_of_a_unit_is_unchanged_by_its_project() -> None:
    groups = [tagged(1, "web")]
    (unit,) = parse_plan(reply(groups=[1], project="web"), groups=groups).units

    assert unit.project == "web"
    assert plan_kind(unit, groups) == Kind(repo="app", tier="unit-test")
