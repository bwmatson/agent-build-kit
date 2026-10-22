"""The graph page draws only a unit's direct edges, and a merged parent only for a kept edge."""

from __future__ import annotations

import re
from pathlib import Path

from agent_build_kit.pipeline.diagram import in_view, render_markdown, render_mermaid
from agent_build_kit.pipeline.unit_store import StoredUnit, UnitStore
from agent_build_kit.pipeline.units import direct_dependencies
from tests.factories import stored_unit as unit

RECORDED = Path(__file__).parent.parent / "fixtures" / "stores" / "recorded_units.json"
EDGE = re.compile(r"^\s+(\w+) (?:-->|-\.->\|merge\||==>\|needs(?:, merge)?\|) (\w+)$", re.MULTILINE)


def node(unit_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "_", unit_id)


def chain_with_a_redundant_ancestor() -> list[StoredUnit]:
    return [
        unit("a/1", change="a", state="in_review"),
        unit("a/2", change="a", state="in_review", depends_on=("a/1",)),
        unit("a/3", change="a", depends_on=("a/1", "a/2")),
    ]


def test_a_unit_that_stores_a_redundant_ancestor_draws_one_edge() -> None:
    diagram = render_mermaid(chain_with_a_redundant_ancestor())

    assert "a_2 --> a_3" in diagram
    assert "a_1 --> a_3" not in diagram


def test_a_merged_parent_is_drawn_only_when_an_edge_to_it_is_kept() -> None:
    reached_through_another = [
        unit("a/1", change="a", state="merged"),
        unit("a/2", change="a", state="merged", depends_on=("a/1",)),
        unit("a/3", change="a", depends_on=("a/1", "a/2")),
    ]
    kept = [
        unit("a/1", change="a", state="merged"),
        unit("a/3", change="a", depends_on=("a/1",)),
    ]

    assert [u.id for u in in_view(reached_through_another)] == ["a/2", "a/3"]
    assert [u.id for u in in_view(kept)] == ["a/1", "a/3"]


def test_a_needs_dependency_is_thick_and_one_the_chain_implies_draws_no_edge() -> None:
    diagram = render_mermaid(
        [
            unit("a/1", change="a", state="in_review"),
            unit("a/2", change="a", state="in_review", depends_on=("a/1",)),
            unit("a/3", change="a", depends_on=("a/1", "a/2"), needs=("a/1", "a/2")),
        ]
    )

    assert "a_2 ==>|needs| a_3" in diagram
    assert "a_1 ==>" not in diagram
    assert "a_1 --> a_3" not in diagram


def test_a_cross_repo_direct_edge_is_dashed_and_the_redundant_one_is_not_drawn() -> None:
    diagram = render_mermaid(
        [
            unit("p/1", change="p", repo="platform", state="in_review"),
            unit("a/1", change="a", state="in_review", depends_on=("p/1",)),
            unit("a/2", change="a", depends_on=("p/1", "a/1")),
        ]
    )

    assert "p_1 -.->|merge| a_1" in diagram
    assert "a_1 --> a_2" in diagram
    assert "p_1 -.->|merge| a_2" not in diagram


def test_the_legend_says_a_needs_the_chain_implies_draws_no_edge_and_keeps_the_rest() -> None:
    page = render_markdown(chain_with_a_redundant_ancestor())

    legend = page.split("## Legend")[1].split("## Waiting")[0]
    assert "no edge" in legend
    assert "`needs` (`==>`) is a dependency its dependent wrote as a `Needs:` line" in legend
    assert "An edge to a unit a replan\n  replaced is drawn from the unit that carries" in legend


def test_the_graph_of_a_recorded_store_draws_each_units_direct_dependencies(
    tmp_path: Path,
) -> None:
    copy = tmp_path / "units.json"
    copy.write_text(RECORDED.read_text())
    units = UnitStore(copy).all()

    diagram = render_mermaid(units)

    drawn: dict[str, set[str]] = {}
    for parent, child in EDGE.findall(diagram):
        drawn.setdefault(child, set()).add(parent)
    for u in units:
        expected = {node(d) for d in direct_dependencies(u, units)}
        assert drawn.get(node(u.id), set()) == expected, u.id
    assert drawn["feature_3"] == {"feature_2"}
