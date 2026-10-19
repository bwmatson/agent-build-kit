"""A planned integration-test unit is calibrated as the same unit tagged unit-test."""

from __future__ import annotations

import json

import pytest

from agent_build_kit.pipeline.planner import PlannerError, parse_plan, plan_kind
from agent_build_kit.pipeline.unit_size import Calibration, Kind
from agent_build_kit.pipeline.units import Unit
from agent_build_kit.pipeline.work_graph import TaskGroup
from tests.calibration_support import limits

POOLED = Kind(repo="app", tier="unit-test")
RATIOS = {POOLED: Calibration(ratio=1.5, samples=20)}


def groups(kind: str) -> list[TaskGroup]:
    return [
        TaskGroup(number=1, repo="app", tier=kind, title="A", line=3, task_count=2),
        TaskGroup(number=2, repo="app", tier=kind, title="B", line=9, task_count=2),
    ]


def reply(kind: str, estimate: int) -> str:
    unit = {
        "id": "c/1",
        "change": "c",
        "title": "A unit",
        "repo": "app",
        "tier": kind,
        "groups": [1, 2],
        "estimated_lines": estimate,
    }
    return json.dumps({"units": [unit]})


def planned(kind: str) -> Unit:
    return Unit(
        id="c/1",
        change="c",
        title="A unit",
        repo="app",
        tier=kind,
        groups=(1, 2),
        estimated_lines=100,
    )


def test_both_kinds_of_a_planned_unit_have_the_same_calibration_kind() -> None:
    assert plan_kind(planned("integration-test"), groups("integration-test")) == plan_kind(
        planned("unit-test"), groups("unit-test")
    )
    assert plan_kind(planned("integration-test"), None).tier == "unit-test"


def test_an_integration_test_unit_is_checked_by_the_unit_test_ratio() -> None:
    kind = "integration-test"
    limits(max_unit_lines=750)

    with pytest.raises(PlannerError, match="ceiling") as rejected:
        parse_plan(reply(kind, 600), groups=groups(kind), calibrations=RATIOS)
    assert "900" in str(rejected.value)

    plan = parse_plan(reply(kind, 480), groups=groups(kind), calibrations=RATIOS)
    assert [unit.id for unit in plan.units] == ["c/1"]
