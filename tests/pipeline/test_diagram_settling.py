"""A settling unit is drawn, and so is the edge to a dependent (spec: merged-waits-for-ci)."""

from agent_build_kit.pipeline.diagram import render_mermaid
from agent_build_kit.pipeline.vocabulary import state_label
from tests.factories import new_unit


def test_a_settling_unit_and_its_planned_dependent_are_drawn_with_the_edge() -> None:
    parent = new_unit("base/1", state="settling", pr=1)
    child = new_unit("kid/1", depends_on=("base/1",))

    diagram = render_mermaid([parent, child])

    assert "base_1[" in diagram
    assert "kid_1[" in diagram
    assert "base_1 --> kid_1" in diagram


def test_the_settling_label_says_it_waits_for_its_checks() -> None:
    label = state_label("settling")

    assert label is not None
    assert label.name == "settling"
    assert "checks" in label.description
