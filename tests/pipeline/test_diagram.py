"""The dependency diagram.

Units are tracked locally rather than as GitHub issues, so nothing renders the
graph for free. This does: one mermaid diagram of every unit across both
repos, what it waits on, and where it has got to.

It is the thing a human looks at to answer "what is the pipeline doing and
what is it stuck behind", so the tests are mostly about legibility — grouping
by repo, marking cross-repo edges, and staying diff-friendly when it is
regenerated.
"""

from pathlib import Path

from agent_build_kit.pipeline.diagram import in_view, render_markdown, render_mermaid, write_page
from tests.factories import stored_unit as unit


def test_units_are_grouped_by_repo() -> None:
    """Which repo a unit lands in is the first thing to know, because it
    decides what can stack and what has to wait for a merge."""
    diagram = render_mermaid([unit("a", repo="app"), unit("b", repo="platform")])

    assert "subgraph app" in diagram
    assert "subgraph platform" in diagram


def test_a_node_says_what_the_unit_is() -> None:
    diagram = render_mermaid([unit("add-marker/1", title="Register the marker", tier="tier2")])

    assert "add-marker/1" in diagram
    assert "Register the marker" in diagram
    assert "tier2" in diagram


def test_node_ids_are_safe_for_mermaid() -> None:
    """Unit ids contain a slash; mermaid would read it as syntax."""
    diagram = render_mermaid(
        [unit("add-marker/1"), unit("add-marker/2", depends_on=("add-marker/1",))]
    )

    assert "add-marker/1[" not in diagram
    assert "add_marker_1" in diagram


def test_dependencies_become_edges() -> None:
    diagram = render_mermaid([unit("a"), unit("b", depends_on=("a",))])

    assert "a --> b" in diagram.replace("_", "")


def test_a_cross_repo_edge_is_drawn_differently() -> None:
    """Same-repo dependencies stack; cross-repo ones wait for a merge. Drawing
    them the same way would hide the slowest edges in the graph."""
    diagram = render_mermaid(
        [
            unit("a", repo="platform"),
            unit("b", repo="app", depends_on=("a",)),
        ]
    )

    assert "-.->" in diagram, "cross-repo edges are dashed"


def test_a_merge_gated_edge_is_drawn_and_labelled() -> None:
    """A unit waiting on a same-repo dependency that is already in review
    needs the page to say why."""
    diagram = render_mermaid(
        [
            unit("a", state="in_review"),
            unit("b", depends_on=("a",), merge_before=("a",)),
        ]
    )

    assert "a ==>|merged| b" in diagram
    assert "class b blocked" in diagram
    assert "a --> b" not in diagram


def test_the_legend_explains_the_merge_gated_edge() -> None:
    page = render_markdown(
        [unit("a", state="in_review"), unit("b", depends_on=("a",), merge_before=("a",))]
    )

    legend = page.split("## Legend")[1].split("## Waiting")[0]
    assert "==>" in legend
    assert "merge" in legend.lower()


def test_state_is_visible_without_reading_the_labels() -> None:
    diagram = render_mermaid(
        [
            unit("a", state="merged"),
            unit("b", state="in_review"),
            unit("c", state="running"),
            unit("d", state="planned"),
        ]
    )

    assert "classDef merged" in diagram
    assert "class a_ merged".replace("_ ", " ") in diagram.replace("a ", "a ")


def test_a_blocked_unit_can_be_told_from_a_ready_one() -> None:
    """The question the diagram exists to answer is "what is stuck behind
    what", so a unit waiting on an unmerged cross-repo edge should read
    differently from one that can start now."""
    diagram = render_mermaid(
        [
            unit("a", repo="platform", state="in_review"),
            unit("b", repo="app", depends_on=("a",), state="planned"),
        ]
    )

    assert "blocked" in diagram


def test_an_empty_graph_still_renders() -> None:
    """A first run has no units; the page should say so rather than break."""
    diagram = render_mermaid([])

    assert "flowchart" in diagram


def test_output_is_stable_for_the_same_input() -> None:
    """It is committed and regenerated often, so unstable ordering would make
    every diff noise."""
    units = [unit("b", repo="platform"), unit("a", repo="app")]

    assert render_mermaid(units) == render_mermaid(list(reversed(units)))


def test_the_markdown_page_carries_a_legend_and_a_count() -> None:
    """A diagram with no legend needs its author present to be read."""
    page = render_markdown([unit("a", state="in_review"), unit("b")])

    assert "```mermaid" in page
    assert "2 units" in page
    assert "Legend" in page
    assert "generated" in page.lower()


def test_the_page_lists_what_is_waiting_on_review() -> None:
    """Open PRs are deliberately uncapped, so the pile is worth showing."""
    page = render_markdown([unit("a", state="in_review", pr=4)])

    assert "#4" in page


def test_blocked_means_what_the_scheduler_means() -> None:
    """The diagram restated the dependency rule and drifted: a unit whose
    same-repo parent was still in its build/review loop showed as startable,
    while the tick rightly held it back."""
    diagram = render_mermaid([unit("c/1", state="running"), unit("c/2", depends_on=("c/1",))])

    assert "class c_2 blocked" in diagram


def test_a_unit_stopped_mid_loop_is_paused_not_merely_blocked() -> None:
    """Both wait on a parent, but a paused unit has work on its branch and
    will restack before resuming — worth seeing at a glance."""
    paused = unit(
        "c/2",
        depends_on=("c/1",),
        history=({"state": "planned", "at": "t", "note": "held after the build: c/1 is running"},),
    )

    diagram = render_mermaid([unit("c/1", state="running"), paused])

    assert "class c_2 paused_rework" in diagram
    assert "paused-rework" in diagram


def test_a_unit_a_reviewer_took_over_has_its_own_colour() -> None:
    diagram = render_mermaid([unit("c/1", state="held")])

    assert "classDef held" in diagram
    assert "class c_1 held" in diagram


def test_rewriting_an_unchanged_graph_leaves_the_file_alone(tmp_path: Path) -> None:
    """It is rewritten on every store write and committed, so a new timestamp
    alone would be a diff on every tick."""
    out = tmp_path / "graph.md"
    write_page([unit("c/1")], out)
    out.write_text(out.read_text().replace("_Generated", "_Generated earlier"))
    before = out.read_text()

    write_page([unit("c/1")], out)
    assert out.read_text() == before

    write_page([unit("c/1", state="running")], out)
    assert out.read_text() != before


def test_only_unfinished_work_and_its_merged_base_are_in_view() -> None:
    """The graph would otherwise grow with every unit ever planned. What is
    kept is what is still moving, plus the merged unit it stands on."""
    units = [
        unit("old/1", state="merged"),
        unit("c/1", state="merged", depends_on=("old/1",)),
        unit("c/2", state="running", depends_on=("c/1",)),
        unit("c/3", depends_on=("c/2",)),
        unit("c/4", state="unplanned"),
        unit("d/1", state="closed"),
    ]

    assert [u.id for u in in_view(units)] == ["c/1", "c/2", "c/3"]


def test_a_unit_is_coloured_by_the_whole_graph_not_just_what_is_drawn() -> None:
    """A parent left out of the drawing still decides whether its child is
    blocked — a cross-repo parent in review keeps its dependent waiting."""
    parent = unit("a/1", repo="platform", state="in_review")
    child = unit("b/1", depends_on=("a/1",))

    assert "class b_1 blocked" in render_mermaid([child], graph=[parent, child])


def test_the_page_says_how_much_it_left_out() -> None:
    page = render_markdown([unit("a", state="merged"), unit("b", state="running")])

    assert "1 unit in view across 1 repo;" in page
    assert "1 finished" in page


def test_a_pr_link_points_at_the_unit_s_repo() -> None:
    """The page is committed to the planning repo; a relative link resolved
    there, to a PR that does not exist."""
    page = render_markdown([unit("a", repo="platform", state="in_review", pr=16)])

    assert "https://github.com/example/platform/pull/16" in page


def test_a_unit_stopped_by_the_usage_window_says_so() -> None:
    """Told apart from a rework pause: one waits on a unit, the other on the
    clock, and what (if anything) a person should do differs."""
    paused = unit(
        "c/1",
        history=({"state": "planned", "at": "t", "note": "paused before review: usage at 75%"},),
    )

    diagram = render_mermaid([paused])

    assert "class c_1 paused_usage" in diagram
    assert "paused-usage" in diagram


def test_a_failed_unit_stays_in_view_with_the_merged_unit_it_builds_on() -> None:
    """Failed is stuck work, the thing the graph most needs to show. Left out,
    a failed unit vanished and took its merged parent with it."""
    units = [
        unit("c/4", state="merged"),
        unit("c/5", state="failed", depends_on=("c/4",)),
        unit("c/6", depends_on=("c/5",)),
    ]

    assert [u.id for u in in_view(units)] == ["c/4", "c/5", "c/6"]
    assert "class c_5 failed" in render_mermaid(in_view(units), graph=units)
