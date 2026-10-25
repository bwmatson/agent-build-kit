"""The planner's review tier for a unit, and the floor under it (spec: review-tier-estimate)."""

from __future__ import annotations

import json

import pytest

from agent_build_kit.pipeline.planner import PlannerError, parse_graph
from agent_build_kit.pipeline.units import Unit
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


def reply(*members: tuple[int, ...], tier: str | None = None) -> str:
    """A plan with one unit per entry of `members`, each asked for `tier` when it is given."""
    records = []
    for index, numbers in enumerate(members, start=1):
        record: dict = {
            "id": f"feature/{index}",
            "change": "feature",
            "title": "t",
            "repo": "app",
            "tier": "unit-test",
            "groups": list(numbers),
        }
        if tier is not None:
            record["review_tier"] = tier
        records.append(record)
    return json.dumps({"units": records})


def plan(
    *members: tuple[int, ...],
    flags: tuple[str, ...],
    bodies: tuple[str, ...] = (),
    tier: str | None,
) -> list[Unit]:
    return parse_graph(
        reply(*members, tier=tier),
        groups=groups(*flags),
        tasks=tasks_text(*(bodies or (PLAIN,) * len(flags))),
    )


@pytest.mark.parametrize("flag", ["contract", "narrow", "acceptance"])
def test_a_flagged_group_makes_its_units_floor_full(flag: str) -> None:
    units = plan((1,), flags=(flag,), tier=None)

    assert units[0].review_tier == "full"


def test_a_protected_path_in_the_task_text_makes_the_floor_full() -> None:
    units = plan((1,), flags=("",), bodies=(f"Add `{MIGRATION}` for the index.",), tier=None)

    assert units[0].review_tier == "full"


def test_a_unit_takes_the_highest_floor_of_its_groups() -> None:
    with pytest.raises(PlannerError, match=r"feature/1.*group 2.*full"):
        plan((1, 2), flags=("", "contract"), tier="auto")


def test_an_auto_reply_for_a_full_floor_is_refused_naming_unit_group_and_floor() -> None:
    with pytest.raises(PlannerError) as refused:
        plan((1,), flags=("contract",), tier="auto")

    message = str(refused.value)
    assert "feature/1" in message
    assert "group 1" in message
    assert "full" in message


def test_a_light_reply_for_an_unflagged_unit_is_accepted() -> None:
    units = plan((1,), flags=("",), tier="light")

    assert units[0].review_tier == "light"


def test_a_reply_may_raise_a_unit_above_its_floor() -> None:
    units = plan((1,), flags=("",), tier="full")

    assert units[0].review_tier == "full"


def test_an_unknown_value_is_refused_naming_unit_group_and_floor() -> None:
    with pytest.raises(PlannerError) as refused:
        plan((1,), flags=("",), tier="ful")

    message = str(refused.value)
    assert "ful" in message
    assert "feature/1" in message
    assert "group 1" in message
    assert "'auto'" in message


@pytest.mark.parametrize(
    "body",
    [
        "Edit `.github/workflows/ci.yml` to run it.",
        "Add .env for the key.",
        "Update .gitlab-ci.yml.",
        "Change the CI definition (.github/workflows/ci.yml).",
    ],
)
def test_a_protected_path_that_begins_with_a_dot_makes_the_floor_full(body: str) -> None:
    assert plan((1,), flags=("",), bodies=(body,), tier=None)[0].review_tier == "full"
    with pytest.raises(PlannerError, match=r"feature/1.*group 1.*full"):
        plan((1,), flags=("",), bodies=(body,), tier="auto")


def test_an_omitted_value_takes_the_floor() -> None:
    units = plan((1,), (2,), flags=("", "contract"), tier=None)

    assert [u.review_tier for u in units] == ["auto", "full"]
