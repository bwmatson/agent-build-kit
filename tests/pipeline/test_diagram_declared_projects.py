"""The written graph page counts the projects a repo declares, not only those of its units."""

import argparse
from pathlib import Path

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline.diagram import render_mermaid
from agent_build_kit.pipeline.unit_store import UnitStore
from tests.conftest import make_installation
from tests.factories import new_unit


def _page(tmp_path: Path, repo: dict, unit_project: str) -> str:
    inst = make_installation(
        tmp_path,
        planning={"state_dir": ".", "worktree_root": str(tmp_path.parent / "trees")},
        repos={"app": {"path": str(tmp_path / "app"), "slug": "example/app", **repo}},
    )
    UnitStore(tmp_path / "units.json").upsert(
        [new_unit("feature/1", repo="app", project=unit_project)]
    )
    assert cli.cmd_graph(argparse.Namespace(), inst) == 0
    return inst.graph_page.read_text()


def test_a_repo_declaring_web_nests_it_when_every_unit_in_view_is_in_web(tmp_path: Path) -> None:
    page = _page(tmp_path, {"projects": [{"path": "web"}]}, "web")

    assert 'subgraph app__project__web["web"]' in page
    assert page.index("subgraph app\n") < page.index('["web"]')


def test_a_repo_declaring_nothing_stays_flat_for_a_unit_of_an_undeclared_project(
    tmp_path: Path,
) -> None:
    page = _page(tmp_path, {}, "web")

    assert "__project__" not in page


def test_a_declared_project_list_without_the_root_counts_the_root() -> None:
    diagram = render_mermaid(
        [new_unit("feature/1", repo="app", project="web")], projects={"app": ("web",)}
    )

    assert 'subgraph app__project__web["web"]' in diagram
