"""The planner keeps held groups out of units that carry other groups (spec: external-work).

Each refusal is shown beside the accepted plan that separates the groups.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_build_kit.pipeline.external_file import add_hold, blocked_groups
from agent_build_kit.pipeline.planner import PlannerError, parse_graph
from agent_build_kit.pipeline.unit_store import UnitStore
from tests.conftest import make_installation
from tests.external_support import change_in, hold, tasks_with, waits_of
from tests.factories import groups_at, stored_unit


def reply(*members: tuple[int, ...]) -> str:
    """A plan with one unit per entry of `members`."""
    records = [
        {
            "id": f"feature/{index}",
            "change": "feature",
            "title": "t",
            "repo": "app",
            "tier": "unit-test",
            "groups": list(numbers),
        }
        for index, numbers in enumerate(members, start=1)
    ]
    return json.dumps({"units": records})


def plan(*members: tuple[int, ...], external: frozenset[int], groups: int = 3):
    return parse_graph(
        reply(*members),
        groups=groups_at(*[3] * groups),
        tasks=tasks_with(groups),
        external=external,
    )


def test_a_plan_joining_a_held_group_with_a_free_one_is_refused_naming_unit_and_group() -> None:
    with pytest.raises(PlannerError) as refused:
        plan((1,), (2, 3), external=frozenset({2}))

    message = str(refused.value)
    assert "feature/2" in message
    assert "group 2" in message

    assert [unit.groups for unit in plan((1,), (2,), (3,), external=frozenset({2}))] == [
        (1,),
        (2,),
        (3,),
    ]


def test_a_plan_with_the_held_group_alone_is_accepted_and_held_groups_may_share_a_unit() -> None:
    with pytest.raises(PlannerError, match="feature/1"):
        plan((1, 2), (3,), external=frozenset({2}))

    assert [unit.groups for unit in plan((1,), (2, 3), external=frozenset({2, 3}))] == [
        (1,),
        (2, 3),
    ]


def test_a_hold_recorded_first_on_an_empty_folder_makes_the_first_plan_park_every_unit(
    tmp_path: Path,
) -> None:
    inst = make_installation(tmp_path / "planning", planning=dict(state_dir="."))
    folder = change_in(inst.changes_dir, groups=0)
    add_hold(folder, hold("all"))
    (folder / "tasks.md").write_text(tasks_with(3))

    units = plan((1,), (2,), (3,), external=blocked_groups(folder))
    store = UnitStore(inst.state_dir / "units.json")
    store.upsert([stored_unit(unit.id, change="feature", groups=unit.groups) for unit in units])

    waits = waits_of(inst, store)
    assert {uid: wait.reason.value for uid, wait in waits.items()} == {
        "feature/1": "external",
        "feature/2": "external",
        "feature/3": "external",
    }
