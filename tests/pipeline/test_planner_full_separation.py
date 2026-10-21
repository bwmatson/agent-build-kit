"""A unit that holds a group whose floor is `full` holds only such groups, in the plan
(spec: unit-sizing). Each test also shows the plan with the groups apart accepted."""

from __future__ import annotations

import json

import pytest

from agent_build_kit.pipeline.planner import PlannerError, parse_graph
from agent_build_kit.pipeline.work_graph import TaskGroup
from tests.factories import activate_with, groups_at

MIGRATION = "db/migrations/0042_add_index.sql"
PLAIN = "Test: it behaves."


@pytest.fixture(autouse=True)
def review_enabled() -> None:
    activate_with(review={"enabled": True})


def groups(*flags: str) -> list[TaskGroup]:
    return [
        group.model_copy(update={"flag": flag})
        for group, flag in zip(groups_at(*[3] * len(flags)), flags, strict=True)
    ]


def tasks_text(*bodies: str) -> str:
    """A tasks.md whose group N has the task text `bodies[N - 1]`."""
    text = "# Tasks\n\n"
    for number, body in enumerate(bodies, start=1):
        text += f"## {number}. [app] [unit-test] Group {number}\n\n- [ ] {number}.1 {body}\n\n"
    return text


def reply(*members: tuple[int, ...]) -> str:
    """A plan with one unit per entry of `members`, each asking for `full` review."""
    records = [
        {
            "id": f"feature/{index}",
            "change": "feature",
            "title": "t",
            "repo": "app",
            "tier": "unit-test",
            "review_tier": "full",
            "groups": list(numbers),
        }
        for index, numbers in enumerate(members, start=1)
    ]
    return json.dumps({"units": records})


def plan(*members: tuple[int, ...], flags: tuple[str, ...], bodies: tuple[str, ...] = ()) -> None:
    parse_graph(
        reply(*members),
        groups=groups(*flags),
        tasks=tasks_text(*(bodies or (PLAIN,) * len(flags))),
    )


def test_a_protected_path_group_and_an_unflagged_group_in_one_unit_are_refused() -> None:
    bodies = (PLAIN, f"Add `{MIGRATION}` for the index.")

    with pytest.raises(PlannerError) as refused:
        plan((1, 2), flags=("", ""), bodies=bodies)

    message = str(refused.value)
    assert "feature/1" in message
    assert "group 1" in message and "group 2" in message

    plan((1,), (2,), flags=("", ""), bodies=bodies)


def test_a_contract_group_with_an_ordinary_group_is_refused() -> None:
    with pytest.raises(PlannerError) as refused:
        plan((1, 2), flags=("contract", ""))

    message = str(refused.value)
    assert "feature/1" in message
    assert "group 1" in message and "group 2" in message

    plan((1,), (2,), flags=("contract", ""))


def test_two_groups_whose_floors_are_full_are_not_refused_by_this_rule() -> None:
    # The third group is ordinary, so the refusal this rule gives is what is shown first.
    with pytest.raises(PlannerError):
        plan((1, 2, 3), flags=("contract", "narrow", ""))

    plan((1, 2), (3,), flags=("contract", "narrow", ""))
