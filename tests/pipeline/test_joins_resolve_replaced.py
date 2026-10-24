"""A join is refused while a started unit's stored edge resolves to the unit joined onto (spec:
a-replaced-unit-points-to-its-successor)."""

from __future__ import annotations

import pytest

from agent_build_kit.pipeline.joins import JoinContext, JoinRefused, check_joins
from agent_build_kit.pipeline.units import Join, UnitState
from agent_build_kit.pipeline.work_graph import TaskGroup
from tests.factories import ordinary_floor, stored_unit


def group() -> TaskGroup:
    return TaskGroup(number=1, repo="app", tier="unit-test", title="A group", line=3, task_count=2)


def test_a_started_unit_whose_edge_names_a_unit_replaced_by_onto_refuses_the_join() -> None:
    stored = (
        stored_unit("base/1", change="base", groups=(1,)),
        stored_unit("later/1", change="later", groups=(1,), depends_on=("base/1",)),
        stored_unit("old/1", change="old", state=UnitState.UNPLANNED, superseded_by=("base/1",)),
        stored_unit(
            "run/1",
            change="run",
            state=UnitState.RUNNING,
            branch="spec/run/1",
            depends_on=("old/1",),
        ),
    )

    with pytest.raises(JoinRefused, match="run/1 already depends on base/1"):
        check_joins(
            [Join(onto="base/1", unit="later/1")],
            context=JoinContext(stored=stored, catalog={"base": (group(),), "later": (group(),)}),
            plan=[],
            change=None,
            groups=[],
            built=set(),
            floor=ordinary_floor,
        )
