"""A join that carries or joins an `[e2e-test]` group is refused, flagged or not; a pair of
`[unit-test]` groups still joins (spec: unit-joining). Each test refuses first, so none passes
before the rule exists."""

from __future__ import annotations

import pytest

from agent_build_kit.pipeline.joins import JoinContext, JoinRefused, check_joins
from agent_build_kit.pipeline.units import Join
from agent_build_kit.pipeline.work_graph import TaskGroup
from tests.factories import ordinary_floor, stored_unit

UNIT, E2E = "unit-test", "e2e-test"
ALONE = "always has a unit of its own"


def tagged(kind: str, *, flag: str = "") -> TaskGroup:
    return TaskGroup(
        number=1, repo="app", tier=kind, title="A group", line=3, task_count=2, flag=flag
    )


def join_group(group: TaskGroup, onto_group: TaskGroup, *, kind: str) -> None:
    """Join `group`, a group of `feature`, onto the stored unit `base/1` holding `onto_group`."""
    onto = stored_unit("base/1", change="base", tier=kind)
    check_joins(
        [Join(onto="base/1", change="feature", groups=(1,), estimated_lines=100)],
        context=JoinContext(stored=(onto,), catalog={"base": (onto_group,)}),
        plan=[],
        change="feature",
        groups=[group],
        built=set(),
        ceiling=750,
        floor=ordinary_floor,
    )


def join_unit(taken_group: TaskGroup, onto_group: TaskGroup, *, kind: str) -> None:
    """Join the stored unit `later/1` holding `taken_group` onto `base/1` holding `onto_group`."""
    onto = stored_unit("base/1", change="base", tier=kind)
    taken = stored_unit("later/1", change="later", tier=kind, depends_on=("base/1",))
    check_joins(
        [Join(onto="base/1", unit="later/1")],
        context=JoinContext(
            stored=(onto, taken), catalog={"base": (onto_group,), "later": (taken_group,)}
        ),
        plan=[],
        change=None,
        groups=[],
        built=set(),
        ceiling=750,
        floor=ordinary_floor,
    )


def test_a_plain_e2e_group_is_not_joined_onto_an_e2e_unit() -> None:
    with pytest.raises(JoinRefused, match=ALONE) as refused:
        join_group(tagged(E2E), tagged(E2E), kind=E2E)

    assert "group 1" in str(refused.value)

    join_group(tagged(UNIT), tagged(UNIT), kind=UNIT)


@pytest.mark.parametrize(
    ("taken", "onto"), [(E2E, E2E), (UNIT, E2E), (E2E, UNIT)], ids=["both", "onto", "taken"]
)
def test_a_unit_holding_an_e2e_group_on_either_side_is_not_joined(taken: str, onto: str) -> None:
    # Both stored units say `e2e-test`, so only the group each holds tells which side is refused.
    with pytest.raises(JoinRefused, match=ALONE):
        join_unit(tagged(taken), tagged(onto), kind=E2E)

    join_unit(tagged(UNIT), tagged(UNIT), kind=UNIT)


def test_an_e2e_acceptance_group_is_refused_with_the_e2e_message() -> None:
    with pytest.raises(JoinRefused, match=ALONE):
        join_group(tagged(E2E, flag="acceptance"), tagged(E2E), kind=E2E)
    with pytest.raises(JoinRefused, match=ALONE):
        join_group(tagged(E2E), tagged(E2E, flag="acceptance"), kind=E2E)
