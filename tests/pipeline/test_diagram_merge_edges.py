"""The unit graph draws a merge dependency as its own edge (spec: needs-can-wait-for-a-merge):
a merge `Needs:` as `==>|needs, merge|`, a cross-repo edge that is no `Needs:` as a dashed edge
labelled `merge`, a review `Needs:` as `==>|needs|` as before, and the node and legend say so."""

from agent_build_kit.pipeline.diagram import render_markdown, render_mermaid
from tests.factories import new_unit


def edges(diagram: str) -> list[str]:
    return [
        line.strip()
        for line in diagram.splitlines()
        if any(a in line for a in ("-->", "==>", "-.->"))
    ]


def test_a_plain_and_a_merge_needs_are_two_kinds_of_thick_edge() -> None:
    review = new_unit("review/1", state="in_review", pr=1)
    merge = new_unit("merge/1", state="in_review", pr=2)
    child = new_unit(
        "kid/1",
        depends_on=("review/1", "merge/1"),
        needs=("review/1", "merge/1"),
        merge_needs=("merge/1",),
    )

    drawn = edges(render_mermaid([review, merge, child]))

    assert sorted(drawn) == [
        "merge_1 ==>|needs, merge| kid_1",
        "review_1 ==>|needs| kid_1",
    ]


def test_a_cross_repo_edge_that_is_no_needs_is_dashed_and_labelled_merge() -> None:
    lib = new_unit("lib/1", repo="platform", state="in_review", pr=1)
    use = new_unit("use/1", repo="app", depends_on=("lib/1",))
    plain = new_unit("base/1", state="in_review", pr=2)
    stacked = new_unit("top/1", repo="app", depends_on=("base/1",))

    drawn = edges(render_mermaid([lib, use, plain, stacked]))

    assert sorted(drawn) == ["base_1 --> top_1", "lib_1 -.->|merge| use_1"]


def test_the_node_carries_the_merge_wait_and_a_review_wait_keeps_its_text() -> None:
    parent = new_unit("p/1", state="in_review", pr=1)
    merging = new_unit("m/1", depends_on=("p/1",), needs=("p/1",), merge_needs=("p/1",))
    reviewing = new_unit("r/1", depends_on=("p/1",), needs=("p/1",))
    diagram = render_mermaid([parent, merging, reviewing])

    nodes = {line.strip().split("[")[0]: line for line in diagram.splitlines() if "<small>" in line}

    assert "waiting for p group 1 to merge (merge: the Needs: line says merged)" in nodes["m_1"]
    assert "(merge:" not in nodes["r_1"]


def test_the_page_draws_both_edges_and_the_legend_names_both_labels() -> None:
    page = render_markdown(
        [
            new_unit("p/1", state="in_review", pr=1),
            new_unit("q/1", state="in_review", pr=2),
            new_unit("m/1", depends_on=("p/1",), needs=("p/1",), merge_needs=("p/1",)),
            new_unit("lib/1", repo="platform", state="in_review", pr=3),
            new_unit("use/1", depends_on=("lib/1",)),
            new_unit("r/1", depends_on=("q/1",), needs=("q/1",)),
        ]
    )

    diagram, legend = page.split("## Legend")
    assert "==>|needs, merge|" in diagram
    assert "-.->|merge|" in diagram
    assert "==>|needs|" in diagram
    assert "`needs, merge`" in legend
    assert "`merge`" in legend
