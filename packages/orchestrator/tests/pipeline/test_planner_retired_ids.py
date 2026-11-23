"""A retired unit's id is taken: the planner is shown it, and a plan that uses it is refused as
invalid (spec: a-started-unit-keeps-its-groups)."""

from __future__ import annotations

import json

import pytest

from agent_build_kit.pipeline.planner import PlannerError, in_flight_item, plan_round
from agent_build_kit.pipeline.units import UnitState
from tests.factories import stored_unit

CHANGES = {"add-marker": "## 1. [app] [unit-test] Register the marker\n"}


def plan_using(*ids: str) -> str:
    return json.dumps(
        {
            "units": [
                {
                    "id": uid,
                    "change": "add-marker",
                    "title": "Register the marker",
                    "repo": "app",
                    "tier": "unit-test",
                    "depends_on": [],
                    "estimated_lines": 120,
                    "groups": [1],
                }
                for uid in ids
            ]
        }
    )


def retired_item(uid: str = "add-marker/1") -> dict:
    retired = stored_unit(uid, change="add-marker", state=UnitState.RETIRED, branch=f"spec/{uid}")
    return in_flight_item(retired, [retired])


def test_the_prompt_lists_the_retired_ids_as_taken() -> None:
    captured: list[str] = []

    def ask(prompt: str) -> str:
        captured.append(prompt)
        return plan_using("add-marker/2")

    plan_round(changes=CHANGES, in_flight=[retired_item("add-marker/1")], run_claude=ask)

    assert any(
        "add-marker/1" in line and "retired" in line and "taken" in line
        for line in captured[0].splitlines()
    ), "a line says the retired id is taken"


def test_a_plan_using_a_retired_id_is_refused_and_one_using_none_is_accepted() -> None:
    in_flight = [retired_item("add-marker/1")]

    with pytest.raises(PlannerError, match=r"add-marker/1"):
        plan_round(
            changes=CHANGES, in_flight=in_flight, run_claude=lambda _: plan_using("add-marker/1")
        )

    plan = plan_round(
        changes=CHANGES, in_flight=in_flight, run_claude=lambda _: plan_using("add-marker/2")
    )
    assert [unit.id for unit in plan.units] == ["add-marker/2"]
