"""Edges between projects: plain within a repo, dashed across repos, thick for `Needs:`."""

from agent_build_kit.pipeline.diagram import render_mermaid
from tests.factories import stored_unit as unit

_PROJECTS = {"app": (".", "web"), "platform": (".",)}


def test_a_dependency_between_two_projects_of_one_repo_is_plain() -> None:
    diagram = render_mermaid(
        [
            unit("a", repo="app", state="in_review"),
            unit("b", repo="app", project="web", depends_on=("a",)),
        ],
        projects=_PROJECTS,
    )

    assert "a --> b" in diagram
    assert "-.->" not in diagram


def test_a_dependency_across_repos_is_dashed() -> None:
    diagram = render_mermaid(
        [
            unit("a", repo="platform", state="in_review"),
            unit("b", repo="app", project="web", depends_on=("a",)),
        ],
        projects=_PROJECTS,
    )

    assert "a -.->|merge| b" in diagram


def test_a_needs_edge_between_projects_keeps_its_thick_style() -> None:
    diagram = render_mermaid(
        [
            unit("a", repo="app", state="in_review"),
            unit("b", repo="app", project="web", depends_on=("a",), needs=("a",)),
        ],
        projects=_PROJECTS,
    )

    assert "a ==>|needs| b" in diagram
