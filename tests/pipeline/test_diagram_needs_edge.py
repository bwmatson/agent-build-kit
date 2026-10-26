"""The graph page marks a dependency written as a `Needs:` line.

A thick edge labelled `needs` tells a stated dependency from one the planner
inferred, which is drawn plainly.
"""

from pathlib import Path

from agent_build_kit.pipeline.diagram import render_markdown, render_mermaid
from tests.factories import stored_unit as unit


def test_a_needs_dependency_is_thick_and_labelled_and_an_inferred_one_is_plain() -> None:
    diagram = render_mermaid(
        [
            unit("a", state="in_review"),
            unit("b", state="in_review"),
            unit("c", depends_on=("a", "b"), needs=("a",)),
        ]
    )

    assert "a ==>|needs| c" in diagram
    assert "b --> c" in diagram
    assert "b ==>" not in diagram
    assert "|merged|" not in diagram


def test_the_legend_explains_the_needs_edge() -> None:
    page = render_markdown(
        [unit("a", state="in_review"), unit("b", depends_on=("a",), needs=("a",))]
    )

    legend = page.split("## Legend")[1].split("## Waiting")[0]
    assert "`needs`" in legend
    assert "==>" in legend
    assert "`merged`" not in legend


def test_the_unit_graph_doc_describes_the_needs_edge() -> None:
    doc = (Path(__file__).parents[2] / "docs" / "designs/unit-graph.md").read_text()

    assert "==>|needs|" in doc
    assert "merge_before" not in doc
