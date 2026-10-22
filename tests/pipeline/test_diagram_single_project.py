"""A repo with one project, and a workspace of such repos, is drawn as it was before projects."""

from agent_build_kit.pipeline.diagram import render_mermaid
from tests.factories import stored_unit as unit

_ROOT_PROJECTS = """\
flowchart LR
    subgraph app
        b["b<br/>Register the marker<br/><small>unit-test · blocked, waiting for add-marker group \
1 to merge (merge: another repository)</small>"]
    end
    subgraph platform
        a["a<br/>Register the marker<br/><small>unit-test · in-review</small>"]
    end
    a -.->|merge| b
"""

_UNDECLARED_PROJECT = """\
flowchart LR
    subgraph app
        c["c<br/>Register the marker<br/><small>unit-test · planned</small>"]
    end
    subgraph platform
        a["a<br/>Register the marker<br/><small>unit-test · in-review</small>"]
    end
"""


def test_repos_with_one_project_each_are_drawn_byte_for_byte_as_before() -> None:
    diagram = render_mermaid(
        [unit("a", repo="platform", state="in_review"), unit("b", repo="app", depends_on=("a",))],
        projects={"app": (".",), "platform": (".",)},
    )

    assert diagram.startswith(_ROOT_PROJECTS)
    assert "    classDef planned " in diagram


def test_a_unit_of_an_undeclared_project_in_a_repo_declaring_none_is_not_nested() -> None:
    diagram = render_mermaid(
        [unit("a", repo="platform", state="in_review"), unit("c", repo="app", project="web")],
        projects={"app": (), "platform": ()},
    )

    assert diagram.startswith(_UNDECLARED_PROJECT)
