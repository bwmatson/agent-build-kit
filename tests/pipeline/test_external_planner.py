"""The planner keeps held groups out of units that carry other groups (spec: external-work).

Each refusal is shown beside the accepted plan that separates the groups.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_build_kit.pipeline.external_file import add_hold, blocked_groups
from agent_build_kit.pipeline.joins import JoinContext, JoinRefused, check_joins
from agent_build_kit.pipeline.planner import PlannerError, parse_graph, parse_plan
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import Join
from tests.conftest import make_installation
from tests.external_support import change_in, hold, tasks_with, waits_of
from tests.factories import groups_at, ordinary_floor, stored_unit, tiered_stored_unit


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


def test_a_join_of_a_held_group_onto_an_unstarted_unit_of_another_change_is_refused() -> None:
    other = tiered_stored_unit("other/1", change="other")
    context = JoinContext(stored=(other,), catalog={"other": tuple(groups_at(3))})
    joined = {"onto": "other/1", "change": "feature", "groups": [2], "estimated_lines": 50}

    def planned(*members: tuple[int, ...], joins: list[dict] | None = None) -> str:
        return json.dumps({**json.loads(reply(*members)), "joins": joins or []})

    def parse(output: str) -> None:
        parse_plan(
            output,
            groups=groups_at(3, 3, 3),
            tasks=tasks_with(3),
            change="feature",
            context=context,
            external=frozenset({2}),
        )

    with pytest.raises(PlannerError) as refused:
        parse(planned((1,), (3,), joins=[joined]))
    assert "group 2" in str(refused.value) and "other/1" in str(refused.value)

    parse(planned((1,), (2,), (3,)))


def test_a_group_join_is_refused_only_when_exactly_one_side_is_held() -> None:
    other = tiered_stored_unit("other/1", change="other")
    join = Join(onto="other/1", change="feature", groups=(2,), estimated_lines=50)

    def check(held_groups: frozenset[int], held_units: frozenset[str]) -> None:
        check_joins(
            [join],
            context=JoinContext(
                stored=(other,),
                catalog={"other": tuple(groups_at(3))},
                external_units=held_units,
            ),
            plan=[],
            change="feature",
            groups=groups_at(3, 3, 3),
            built=set(),
            floor=ordinary_floor,
            external=held_groups,
        )

    with pytest.raises(JoinRefused, match=r"group 2.*other/1"):
        check(frozenset({2}), frozenset())
    with pytest.raises(JoinRefused, match=r"other/1.*group 2"):
        check(frozenset(), frozenset({"other/1"}))
    check(frozenset(), frozenset())
    check(frozenset({2}), frozenset({"other/1"}))


def test_a_unit_join_is_refused_when_exactly_one_side_is_held() -> None:
    parent = tiered_stored_unit("other/1", change="other")
    child = tiered_stored_unit("other/2", change="other", depends_on=("other/1",))
    join = Join(onto="other/1", unit="other/2")

    def check(held: frozenset[str]) -> None:
        check_joins(
            [join],
            context=JoinContext(
                stored=(parent, child),
                catalog={"other": tuple(groups_at(3, 3))},
                external_units=held,
            ),
            plan=[],
            change=None,
            groups=[],
            built=set(),
            floor=ordinary_floor,
        )

    both = r"other/2.*other/1|other/1.*other/2"
    with pytest.raises(JoinRefused, match=both):
        check(frozenset({"other/2"}))
    with pytest.raises(JoinRefused, match=both):
        check(frozenset({"other/1"}))
    check(frozenset())
    check(frozenset({"other/1", "other/2"}))
