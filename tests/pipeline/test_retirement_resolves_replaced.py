"""A dependent whose stored edge names a replaced unit counts as stacked on its successor, for
what retiring the successor leaves behind (spec: a-replaced-unit-points-to-its-successor)."""

from __future__ import annotations

from agent_build_kit.pipeline.retirement import assess
from agent_build_kit.pipeline.unit_store import StoredUnit
from agent_build_kit.pipeline.units import UnitState
from tests.factories import stored_unit


def scene(dependent_state: UnitState, **dependent: object) -> list[StoredUnit]:
    return [
        stored_unit("x/3", change="x", state=UnitState.UNPLANNED, superseded_by=("x/5",)),
        stored_unit("x/5", change="x"),
        stored_unit("d/1", change="d", depends_on=("x/3",), state=dependent_state, **dependent),
    ]


def test_an_unstarted_dependent_of_the_replaced_unit_is_a_dependent_of_the_successor() -> None:
    result = assess("x/5", scene(UnitState.PLANNED))

    assert [(d.id, d.state) for d in result.dependents] == [("d/1", "planned")]
    assert result.refusal == ""


def test_a_started_dependent_of_the_replaced_unit_refuses_retiring_the_successor() -> None:
    result = assess("x/5", scene(UnitState.IN_REVIEW, branch="spec/d/1", pr=4))

    assert result.refusal == "d/1 has started and is stacked on x/5"
