"""The diagram draws an edge to a replaced unit from its successor (spec:
a-replaced-unit-points-to-its-successor)."""

from __future__ import annotations

from agent_build_kit.pipeline.diagram import render_mermaid
from agent_build_kit.pipeline.units import UnitState
from tests.factories import stored_unit


def test_the_edge_of_a_dependent_on_a_replaced_unit_is_drawn_from_the_successor() -> None:
    graph = [
        stored_unit("x/3", change="x", state=UnitState.UNPLANNED, superseded_by=("x/5",)),
        stored_unit("x/5", change="x"),
        stored_unit("d/1", change="d", depends_on=("x/3",)),
    ]

    text = render_mermaid([graph[1], graph[2]], graph=graph)

    assert "x_5 --> d_1" in text
    assert "x_3 --> d_1" not in text
