"""A join is refused across e2e-test splits as it is across repos and kinds, and accepted within
one (spec: unit-joining)."""

from __future__ import annotations

import pytest

from agent_build_kit.pipeline.joins import JoinContext, JoinRefused, check_joins
from agent_build_kit.pipeline.units import Join
from agent_build_kit.pipeline.work_graph import TaskGroup
from tests.factories import ordinary_floor, stored_unit


def tagged(split: str) -> TaskGroup:
    return TaskGroup(
        number=1,
        repo="app",
        tier="e2e-test",
        title="A group",
        line=3,
        task_count=2,
        split=split,
    )


def check_group(group_split: str, onto_split: str) -> None:
    onto = stored_unit("base/1", change="base", tier="e2e-test", split=onto_split)
    check_joins(
        [Join(onto="base/1", change="feature", groups=(1,), estimated_lines=100)],
        context=JoinContext(stored=(onto,), catalog={"base": (tagged(onto_split),)}),
        plan=[],
        change="feature",
        groups=[tagged(group_split)],
        built=set(),
        ceiling=750,
        floor=ordinary_floor,
    )


def check_unit(taken_split: str, onto_split: str) -> None:
    onto = stored_unit("base/1", change="base", tier="e2e-test", split=onto_split)
    taken = stored_unit(
        "later/1", change="later", tier="e2e-test", split=taken_split, depends_on=("base/1",)
    )
    check_joins(
        [Join(onto="base/1", unit="later/1")],
        context=JoinContext(
            stored=(onto, taken),
            catalog={"base": (tagged(onto_split),), "later": (tagged(taken_split),)},
        ),
        plan=[],
        change=None,
        groups=[],
        built=set(),
        ceiling=750,
        floor=ordinary_floor,
    )


@pytest.mark.parametrize("split", ["acp", "rest"])
def test_a_group_of_the_same_split_is_accepted_and_one_of_another_is_not(split: str) -> None:
    other = "rest" if split == "acp" else "acp"
    # Within a split an e2e-test group is still never joined; across splits the split is named.
    with pytest.raises(JoinRefused, match="always has a unit of its own"):
        check_group(split, split)

    with pytest.raises(JoinRefused, match="split"):
        check_group(other, split)


@pytest.mark.parametrize("split", ["acp", "rest"])
def test_an_unstarted_unit_of_the_same_split_is_accepted_and_one_of_another_is_not(
    split: str,
) -> None:
    other = "rest" if split == "acp" else "acp"
    with pytest.raises(JoinRefused, match="always has a unit of its own"):
        check_unit(split, split)

    with pytest.raises(JoinRefused, match="split"):
        check_unit(other, split)


@pytest.mark.parametrize(("group_split", "onto_split"), [("acp", "rest"), ("rest", "acp")])
def test_a_group_of_another_split_is_refused_naming_the_split(
    group_split: str, onto_split: str
) -> None:
    with pytest.raises(JoinRefused, match=rf"group 1 .*{group_split}.*{onto_split}"):
        check_group(group_split, onto_split)


@pytest.mark.parametrize(("taken_split", "onto_split"), [("acp", "rest"), ("claude_code", "acp")])
def test_an_unstarted_unit_of_another_split_is_refused_naming_the_split(
    taken_split: str, onto_split: str
) -> None:
    with pytest.raises(JoinRefused, match=rf"later/1 .*{taken_split}.*{onto_split}"):
        check_unit(taken_split, onto_split)
