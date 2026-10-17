"""The legend says a repo with several projects is drawn with a subgraph for each."""

from agent_build_kit.pipeline.diagram import render_markdown
from tests.factories import stored_unit as unit


def test_the_legend_says_a_repo_with_several_projects_has_a_subgraph_for_each() -> None:
    page = render_markdown([unit("a", repo="app")], projects={"app": (".", "web")})

    legend = page.split("## Legend")[1].split("## Waiting")[0]
    assert "several projects" in legend
    assert "subgraph for each" in legend


def test_the_count_of_repos_is_the_repos_not_their_projects() -> None:
    page = render_markdown(
        [unit("a", repo="app"), unit("b", repo="app", project="web"), unit("c", repo="platform")],
        projects={"app": (".", "web")},
    )

    assert "3 units in view across 2 repos" in page
