"""The graph page shows `priority 0` as it shows any priority other than 3."""

from agent_build_kit.pipeline.diagram import render_mermaid
from tests.factories import stored_unit as unit


def test_the_node_of_a_priority_zero_unit_says_so_and_a_normal_node_does_not() -> None:
    diagram = render_mermaid([unit("a", priority=0), unit("b")])

    nodes = {line.strip().split("[")[0]: line for line in diagram.splitlines() if "[" in line}
    assert "priority 0" in nodes["a"]
    assert "priority" not in nodes["b"]
