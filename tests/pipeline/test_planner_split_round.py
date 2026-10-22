"""A split plan round plans only the held unit's groups, every other group being as built, and
holds each piece to the ceiling and flags of its own tier (spec: split-planning)."""

from __future__ import annotations

import json

import pytest

from agent_build_kit.pipeline.planner import GroupTooLarge, Plan, PlannerError, plan_round
from agent_build_kit.pipeline.verdict import ReviewTier, SplitRequest
from agent_build_kit.pipeline.work_graph import TaskGroup
from tests.factories import stored_unit
from tests.split_plan_support import ALL, TASKS, piece, use_per_tier_sizing

HELD = stored_unit("c/2", change="c", groups=(2, 3, 4))
SPLIT = SplitRequest(
    earned=ReviewTier.FULL, planned=ReviewTier.AUTO, lines=900, ceiling=750, drivers=(3,)
)


@pytest.fixture(autouse=True)
def per_tier_sizing() -> None:
    use_per_tier_sizing()


def planned(*pieces: dict, groups: list[TaskGroup] | None = None) -> Plan:
    return plan_round(
        changes={"c": TASKS},
        in_flight=[],
        groups=groups or ALL,
        split=SPLIT,
        held=HELD,
        run_claude=lambda _: json.dumps({"units": list(pieces)}),
    )


def correct() -> tuple[dict, ...]:
    return (
        piece("c/2-s1", [2], "auto", 200),
        piece("c/2-s2", [3], "full", 300, after=("c/2-s1",)),
        piece("c/2-s3", [4], "auto", 200, after=("c/2-s2",)),
    )


def test_a_plan_of_the_held_units_groups_alone_is_accepted_with_the_rest_as_built() -> None:
    plan = planned(*correct())

    assert [unit.groups for unit in plan.units] == [(2,), (3,), (4,)]
    assert [unit.review_tier for unit in plan.units] == ["auto", "full", "auto"]


def test_a_plan_claiming_a_group_outside_the_held_unit_is_refused_as_built() -> None:
    claiming_five = (*correct()[:2], piece("c/2-s3", [4, 5], "auto", 200, after=("c/2-s2",)))

    with pytest.raises(PlannerError, match="group 5"):
        planned(*claiming_five)


def test_the_ceiling_is_the_ceiling_of_each_pieces_tier() -> None:
    # 3000 lines is fine for an auto piece and would be over the full ceiling.
    big_rest = (
        piece("c/2-s1", [2], "auto", 3000),
        piece("c/2-s2", [3], "full", 300, after=("c/2-s1",)),
        piece("c/2-s3", [4], "auto", 200, after=("c/2-s2",)),
    )
    assert planned(*big_rest).units[0].estimated_lines == 3000

    with pytest.raises(PlannerError, match="750") as refused:
        planned(
            piece("c/2-s1", [2, 3], "full", 800),
            piece("c/2-s2", [4], "auto", 200, after=("c/2-s1",)),
        )
    assert not isinstance(refused.value, GroupTooLarge)


def test_a_single_driver_group_alone_over_the_earned_ceiling_is_too_large() -> None:
    with pytest.raises(GroupTooLarge, match="750"):
        planned(
            piece("c/2-s1", [2], "auto", 200),
            piece("c/2-s2", [3], "full", 800, after=("c/2-s1",)),
            piece("c/2-s3", [4], "auto", 200, after=("c/2-s2",)),
        )


def test_the_flag_check_applies_at_each_pieces_tier() -> None:
    flagged = [
        group.model_copy(update={"flag": "contract"}) if group.number == 2 else group
        for group in ALL
    ]

    with pytest.raises(PlannerError, match="full"):
        planned(*correct(), groups=flagged)
