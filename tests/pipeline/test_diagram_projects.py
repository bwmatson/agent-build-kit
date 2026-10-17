"""A repo with several projects is drawn with a nested subgraph for each project in view."""

from agent_build_kit.pipeline.diagram import render_mermaid
from tests.factories import stored_unit as unit


def _enclosing(diagram: str) -> dict[str, list[str]]:
    """For each unit node line, the `subgraph` lines that enclose it, outermost first."""
    open_blocks: list[str] = []
    found: dict[str, list[str]] = {}
    for raw in diagram.splitlines():
        line = raw.strip()
        if line.startswith("subgraph "):
            open_blocks.append(line)
        elif line == "end":
            open_blocks.pop()
        elif open_blocks and "[" in line:
            found[line.split("[", 1)[0]] = list(open_blocks)
    return found


def test_a_repo_with_two_projects_nests_a_subgraph_for_each() -> None:
    diagram = render_mermaid(
        [unit("a", repo="app"), unit("b", repo="app", project="web")],
        projects={"app": (".", "web")},
    )

    enclosing = _enclosing(diagram)
    assert len(enclosing["a"]) == len(enclosing["b"]) == 2
    assert enclosing["a"][0] == enclosing["b"][0] == "subgraph app"
    assert enclosing["a"][1] != enclosing["b"][1]
    assert enclosing["a"][1].endswith('["."]')
    assert enclosing["b"][1].endswith('["web"]')


def test_a_project_with_no_unit_in_view_has_no_subgraph() -> None:
    diagram = render_mermaid([unit("a", repo="app", project="web")], projects={"app": (".", "web")})

    assert diagram.count("subgraph ") == 2
    assert [len(blocks) for blocks in _enclosing(diagram).values()] == [2]


def test_a_repo_declaring_two_projects_nests_even_when_its_units_are_in_one() -> None:
    diagram = render_mermaid(
        [unit("a", repo="app", project="web"), unit("b", repo="app", project="web")],
        projects={"app": (".", "web")},
    )

    assert {len(blocks) for blocks in _enclosing(diagram).values()} == {2}


def test_units_of_two_undeclared_projects_nest_a_repo_that_declares_none() -> None:
    diagram = render_mermaid(
        [unit("a", repo="app", project="api"), unit("b", repo="app", project="web")],
        projects={"app": ()},
    )

    assert {len(blocks) for blocks in _enclosing(diagram).values()} == {2}


def test_nested_subgraph_ids_clash_with_no_repo_or_unit() -> None:
    diagram = render_mermaid(
        [unit("web", repo="app", project="web"), unit("b", repo="app")],
        projects={"app": (".", "web")},
    )

    ids = [
        line.strip().split()[1]
        for line in diagram.splitlines()
        if line.strip().startswith("subgraph ")
    ]
    nodes = list(_enclosing(diagram))
    assert len(set(ids)) == len(ids)
    assert not set(ids) & set(nodes)


def test_unit_nodes_and_classes_are_the_same_as_without_projects() -> None:
    units = [unit("a", repo="app"), unit("b", repo="app", project="web", depends_on=("a",))]

    nested = render_mermaid(units, projects={"app": (".", "web")})
    plain = render_mermaid(units)

    def node_and_class_lines(text: str) -> list[str]:
        return sorted(
            line.strip()
            for line in text.splitlines()
            if "<br/>" in line or line.strip().startswith(("class ", "classDef "))
        )

    assert node_and_class_lines(nested) == node_and_class_lines(plain)
