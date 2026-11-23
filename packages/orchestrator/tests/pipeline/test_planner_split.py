"""A planned unit records the one e2e-test split its groups share (spec: e2e-split-declaration)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_build_kit.pipeline.planner import PlannerError, parse_plan
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.work_graph import TaskGroup
from tests.factories import unit
from tests.split_workspace import splits_workspace


def e2e_group(number: int, split: str | None = None) -> TaskGroup:
    return TaskGroup(
        number=number,
        repo="app",
        tier="e2e-test",
        title=f"Group {number}",
        line=3 * number,
        task_count=2,
        **({} if split is None else {"split": split}),
    )


def plan_of(*groups_per_unit: list[int]) -> str:
    return json.dumps(
        {
            "units": [
                {
                    "id": f"c/{index}",
                    "change": "c",
                    "title": "A unit",
                    "repo": "app",
                    "tier": "e2e-test",
                    "groups": numbers,
                }
                for index, numbers in enumerate(groups_per_unit, start=1)
            ]
        }
    )


@pytest.fixture(autouse=True)
def declaring_splits(tmp_path: Path) -> None:
    splits_workspace(tmp_path / "planning")


def test_a_unit_planned_from_groups_in_acp_records_acp() -> None:
    plan = parse_plan(plan_of([1], [2]), groups=[e2e_group(1, "acp"), e2e_group(2, "acp")])

    assert [u.split for u in plan.units] == ["acp", "acp"]


def test_groups_of_different_splits_are_separate_units_each_with_its_own() -> None:
    groups = [e2e_group(1, "claude_code"), e2e_group(2, "acp"), e2e_group(3), e2e_group(4, "rest")]

    plan = parse_plan(plan_of([1], [2], [3], [4]), groups=groups)

    # A group with no line, or with `rest` written out, is in rest.
    assert [u.split for u in plan.units] == ["claude_code", "acp", "rest", "rest"]


def test_a_plan_with_groups_of_two_splits_in_one_unit_is_refused_naming_groups_and_splits() -> None:
    with pytest.raises(PlannerError) as refused:
        parse_plan(plan_of([1, 2]), groups=[e2e_group(1, "claude_code"), e2e_group(2, "acp")])

    message = str(refused.value)
    assert "c/1" in message
    assert "group 1" in message
    assert "group 2" in message
    assert "claude_code" in message
    assert "acp" in message


def test_a_unit_planned_in_a_split_is_stored_with_it_and_a_store_from_before_reads_rest(
    tmp_path: Path,
) -> None:
    path = tmp_path / "units.json"
    (planned,) = parse_plan(plan_of([1]), groups=[e2e_group(1, "acp")]).units
    UnitStore(path).upsert([planned, unit("feature/1", change="feature")])
    stored = json.loads(path.read_text())
    for record in stored["units"]:
        if record["id"] == "feature/1":
            record.pop("split", None)
    path.write_text(json.dumps(stored))

    store = UnitStore(path)
    assert (store.get("c/1").split, store.get("feature/1").split) == ("acp", "rest")
