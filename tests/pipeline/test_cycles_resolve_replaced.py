"""A plan edge that closes a cycle only through the successor of a replaced unit a stored unit
depends on is dropped, with the cycle named (spec: a-replaced-unit-points-to-its-successor)."""

from __future__ import annotations

from agent_build_kit.pipeline.cycles import drop_cycle_edges
from agent_build_kit.pipeline.units import UnitState
from tests.factories import stored_unit, unit


def test_an_edge_back_to_a_unit_that_depends_on_the_replaced_one_is_dropped() -> None:
    stored = [
        stored_unit("o/1", change="o", state=UnitState.UNPLANNED, superseded_by=("p/1",)),
        stored_unit("p/1", change="p"),
        stored_unit("s/1", change="s", state=UnitState.RUNNING, depends_on=("o/1",)),
    ]

    result = drop_cycle_edges([unit("p/1", change="p", depends_on=("s/1",))], stored, {})

    assert [(e.unit, e.dependency, e.cycle) for e in result.dropped] == [
        ("p/1", "s/1", ("p/1", "s/1", "p/1"))
    ]
    assert result.units[0].depends_on == ()
