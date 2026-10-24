"""A join yields a unit expected to get the higher of the two tiers and is held to that tier's
ceiling after calibration; a floor-`full` group is never joined to a lower one (spec:
review-tier-ceilings). Each case goes through `parse_plan`, the way the planner's reply reaches
the join check."""

from __future__ import annotations

import json

import pytest

from agent_build_kit.pipeline.joins import JoinContext
from agent_build_kit.pipeline.planner import PlannerError, parse_plan
from agent_build_kit.pipeline.unit_size import Calibration, Kind
from agent_build_kit.pipeline.work_graph import TaskGroup
from tests.factories import stored_unit
from tests.tier_ceiling_support import GROUPS, configure

MIGRATION = "db/migrations/0042_add_index.sql"
RATIOS = {Kind(repo="app", tier="unit-test"): Calibration(ratio=1.5, samples=20)}
OTHER_KIND = {Kind(repo="app", tier="e2e-test"): Calibration(ratio=1.5, samples=20)}


@pytest.fixture(autouse=True)
def per_tier_sizing() -> None:
    configure(enabled=True)


def catalog_group(number: int) -> TaskGroup:
    return TaskGroup(
        number=number, repo="app", tier="unit-test", title="A group", line=3, task_count=2
    )


def join_units(
    onto_tier: str,
    taken_tier: str,
    *,
    onto_lines: int = 1200,
    taken_lines: int = 1300,
    found: dict[Kind, Calibration] | None = None,
) -> None:
    """Join `later/1` (a unit not started, waiting on `base/1`) onto `base/1`."""
    onto = stored_unit(
        "base/1", change="base", groups=(1,), review_tier=onto_tier, estimated_lines=onto_lines
    )
    taken = stored_unit(
        "later/1",
        change="later",
        groups=(2,),
        review_tier=taken_tier,
        estimated_lines=taken_lines,
        depends_on=("base/1",),
    )
    context = JoinContext(
        stored=(onto, taken),
        catalog={"base": (catalog_group(1),), "later": (catalog_group(2),)},
    )
    reply = json.dumps({"units": [], "joins": [{"onto": "base/1", "unit": "later/1"}]})
    parse_plan(reply, groups=[], context=context, calibrations=found)


def tasks_text(*bodies: str) -> str:
    text = "# Tasks\n\n"
    for number, body in enumerate(bodies, start=1):
        text += f"## {number}. [app] [unit-test] Group {number}\n\n- [ ] {number}.1 {body}\n\n"
    return text


def join_group(
    onto_tier: str,
    lines: int,
    *,
    onto_lines: int = 1500,
    bodies: tuple[str, ...] = ("Test: it.", "Test: it.", "Test: it."),
    found: dict[Kind, Calibration] | None = None,
) -> None:
    """Join group 3 of `feature` onto `base/1`, with groups 1 and 2 as a unit of their own."""
    onto = stored_unit(
        "base/1", change="base", groups=(1,), review_tier=onto_tier, estimated_lines=onto_lines
    )
    context = JoinContext(stored=(onto,), catalog={"base": (catalog_group(1),)})
    unit = {
        "id": "feature/1",
        "change": "feature",
        "title": "A unit",
        "repo": "app",
        "tier": "unit-test",
        "estimated_lines": 100,
        "groups": [1, 2],
    }
    join = {"onto": "base/1", "change": "feature", "groups": [3], "estimated_lines": lines}
    parse_plan(
        json.dumps({"units": [unit], "joins": [join]}),
        groups=GROUPS,
        change="feature",
        context=context,
        calibrations=found,
        tasks=tasks_text(*bodies),
    )


def refusal(*args, **kwargs) -> str:
    with pytest.raises(PlannerError) as refused:
        join_units(*args, **kwargs)
    return str(refused.value)


@pytest.mark.parametrize(("onto_tier", "taken_tier"), [("light", "auto"), ("auto", "light")])
def test_a_light_unit_joined_with_an_auto_unit_is_held_to_2000_naming_the_tier(
    onto_tier: str, taken_tier: str
) -> None:
    message = refusal(onto_tier, taken_tier)

    assert "light" in message
    assert "2000" in message


def test_a_light_and_auto_join_under_2000_is_accepted() -> None:
    join_units("light", "auto", onto_lines=900, taken_lines=1000)


def test_two_auto_units_combined_at_2500_are_accepted() -> None:
    join_units("auto", "auto")


def test_two_full_units_are_held_to_750() -> None:
    message = refusal("full", "full", onto_lines=300, taken_lines=500)

    assert "full" in message
    assert "750" in message


def test_a_group_counts_at_its_floor_so_it_does_not_lower_the_units_tier() -> None:
    # Group 3 is ordinary (floor auto); the unit it joins stays `light`, held to 2000.
    with pytest.raises(PlannerError) as refused:
        join_group("light", 600)

    assert "light" in str(refused.value)
    assert "2000" in str(refused.value)

    join_group("light", 400)


def test_a_group_joined_onto_an_auto_unit_is_held_to_the_auto_ceiling() -> None:
    join_group("auto", 1500, onto_lines=1500)


def test_a_ratio_applies_to_the_receiving_units_kind() -> None:
    # 3400 raw is under 5000 and 5100 at the ratio of 1.5.
    with pytest.raises(PlannerError) as refused:
        join_units("auto", "auto", onto_lines=1700, taken_lines=1700, found=RATIOS)

    message = str(refused.value)
    for named in ("5100", "5000", "1.50", "20"):
        assert named in message


def test_a_ratio_of_another_kind_does_not_apply() -> None:
    join_units("auto", "auto", onto_lines=1700, taken_lines=1700, found=OTHER_KIND)


def test_a_group_whose_floor_is_full_is_not_joined_to_a_lower_unit() -> None:
    bodies = ("Test: it.", "Test: it.", f"Add `{MIGRATION}` for the index.")

    with pytest.raises(PlannerError) as refused:
        join_group("auto", 100, bodies=bodies)

    assert "group 3" in str(refused.value)

    join_group("auto", 100)


@pytest.mark.parametrize(("onto_tier", "taken_tier"), [("full", "auto"), ("auto", "full")])
def test_a_full_unit_is_not_joined_with_a_unit_that_is_not(onto_tier: str, taken_tier: str) -> None:
    message = refusal(onto_tier, taken_tier, onto_lines=100, taken_lines=100)

    assert "floor is `full`" in message
    assert "floor is lower" in message


def test_two_full_units_are_joined_when_they_fit() -> None:
    join_units("full", "full", onto_lines=100, taken_lines=100)


def test_a_group_is_not_joined_onto_a_full_unit() -> None:
    with pytest.raises(PlannerError) as refused:
        join_group("full", 100, onto_lines=100)

    message = str(refused.value)
    assert "base/1, whose floor is `full`, with group 3, whose floor is lower" in message


def test_a_protected_path_group_is_joined_onto_a_full_unit() -> None:
    join_group(
        "full", 100, onto_lines=100, bodies=("Test: it.", "Test: it.", f"Add `{MIGRATION}`.")
    )


def test_a_join_does_not_mix_floors_among_its_own_groups() -> None:
    onto = stored_unit(
        "base/1", change="base", groups=(1,), review_tier="full", estimated_lines=100
    )
    context = JoinContext(stored=(onto,), catalog={"base": (catalog_group(1),)})
    unit = {
        "id": "feature/1",
        "change": "feature",
        "title": "A unit",
        "repo": "app",
        "tier": "unit-test",
        "estimated_lines": 100,
        "groups": [1, 2],
    }
    join = {"onto": "base/1", "change": "feature", "groups": [3, 4], "estimated_lines": 100}
    tasks = tasks_text("Test: it.", "Test: it.", f"Add `{MIGRATION}`.", "Test: it.")

    with pytest.raises(PlannerError) as refused:
        parse_plan(
            json.dumps({"units": [unit], "joins": [join]}),
            groups=[*GROUPS, catalog_group(4)],
            change="feature",
            context=context,
            tasks=tasks,
        )

    message = str(refused.value)
    assert "group 3 and base/1, whose floor is `full`, with group 4" in message
