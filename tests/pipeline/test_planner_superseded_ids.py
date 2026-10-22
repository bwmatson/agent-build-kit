"""A plan of any change that uses the id of a superseded unit is refused naming it; a change with
no superseded unit is unaffected (spec: unit-superseding)."""

from __future__ import annotations

import json

import pytest

from agent_build_kit.pipeline.planner import PlannerError, in_flight_item, plan_round
from agent_build_kit.pipeline.units import UnitState
from tests.factories import stored_unit

CHANGES = {"feature": "## 1. [app] [unit-test] Register the marker\n"}


def plan_using(label: str) -> str:
    return json.dumps(
        {
            "units": [
                {
                    "id": label,
                    "change": "feature",
                    "title": "Register the marker",
                    "repo": "app",
                    "tier": "unit-test",
                    "depends_on": [],
                    "estimated_lines": 120,
                    "groups": [1],
                }
            ]
        }
    )


def item(uid: str, *, pieces: tuple[str, ...]) -> dict:
    unit = stored_unit(
        uid, change="add-marker", state=UnitState.CLOSED, branch=f"spec/{uid}", superseded_by=pieces
    )
    return in_flight_item(unit, [unit])


def test_a_plan_using_a_superseded_id_is_refused_naming_it_and_a_plan_using_none_is_not() -> None:
    superseded = [item("add-marker/3", pieces=("add-marker/3-s1", "add-marker/3-s2"))]

    with pytest.raises(PlannerError, match=r"add-marker/3\b"):
        plan_round(
            changes=CHANGES, in_flight=superseded, run_claude=lambda _: plan_using("add-marker/3")
        )

    plan = plan_round(
        changes=CHANGES, in_flight=superseded, run_claude=lambda _: plan_using("feature/1")
    )
    assert [unit.groups for unit in plan.units] == [(1,)]


def test_a_closed_unit_that_was_not_superseded_does_not_take_its_id_in_this_check() -> None:
    superseded = [item("add-marker/3", pieces=("add-marker/3-s1",))]
    closed = [item("add-marker/4", pieces=())]

    with pytest.raises(PlannerError, match=r"add-marker/3\b"):
        plan_round(
            changes=CHANGES,
            in_flight=[*closed, *superseded],
            run_claude=lambda _: plan_using("add-marker/3"),
        )
    plan = plan_round(
        changes=CHANGES, in_flight=closed, run_claude=lambda _: plan_using("add-marker/4")
    )
    assert [unit.groups for unit in plan.units] == [(1,)]
