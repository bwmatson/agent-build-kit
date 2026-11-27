"""Building a project's graph over the files a git checkout holds."""

from collections.abc import Sequence
from pathlib import Path

import pytest

from agent_build_kit.codemap.build import build_graph
from agent_build_kit.codemap.graph import (
    Edge,
    EntryPoint,
    FileFacts,
    Reading,
    Symbol,
    dump,
)
from agent_build_kit.config import ProjectConfig
from tests.factories import git, init_repo

APP = ProjectConfig(path="app")
WEB = ProjectConfig(path="app/web")
ROOT = ProjectConfig(path=".")


class FakeReader:
    """Records the files it is given and answers with fixed facts."""

    suffixes: tuple[str, ...] = (".py", ".json", ".md")

    def __init__(self) -> None:
        self.calls: list[tuple[Path, list[str], list[str]]] = []

    def read(self, root: Path, sources: Sequence[str], tests: Sequence[str]) -> Reading:
        self.calls.append((root, list(sources), list(tests)))
        mod = "pkg/mod.py"
        return Reading(
            files=tuple(
                FileFacts(
                    path=path,
                    lines=10,
                    tests=("tests/test_mod.py",) if path == mod else (),
                    symbols=(
                        (
                            Symbol(
                                kind="class", name="C", span=(1, 5), lines=5, signature="class C"
                            ),
                            Symbol(
                                kind="function",
                                name="C.m",
                                span=(2, 3),
                                lines=2,
                                signature="def m(self)",
                            ),
                            Symbol(
                                kind="function", name="f", span=(7, 8), lines=2, signature="def f()"
                            ),
                        )
                        if path == mod
                        else ()
                    ),
                )
                for path in sources
            ),
            edges=(
                Edge(kind="imports", source="pkg/use.py", target=mod),
                Edge(kind="invokes", source="pkg/use.py", target="pkg/gone.py::g"),
            ),
            entry_points=(
                EntryPoint(
                    kind="script", name="ok", path="pyproject.toml", line=1, target=f"{mod}::f"
                ),
                EntryPoint(
                    kind="script",
                    name="bad",
                    path="pyproject.toml",
                    line=2,
                    target="pkg/gone.py::g",
                ),
            ),
        )


def has_tests_folder(path: str) -> bool:
    return "tests" in Path(path).parts


def write(root: Path, *paths: str) -> None:
    for path in paths:
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_text("x = 1\n")


@pytest.fixture
def checkout(tmp_path: Path) -> Path:
    repo = init_repo(tmp_path / "repo")
    write(
        repo,
        "app/pkg/mod.py",
        "app/tests/test_mod.py",
        "app/pkg/data.txt",
        "app/gone.py",
        "app/web/page.py",
        "app/.codemap.json",
        "app/pkg/CODEMAP.md",
        "app/build/out.py",
        "app/only_tests/tests/test_x.py",
        "top.py",
    )
    (repo / ".gitignore").write_text("build/\nignored.py\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "base")
    (repo / "app/gone.py").unlink()
    write(repo, "app/pkg/use.py", "app/ignored.py")
    return repo


def test_a_project_reads_its_own_live_source_files_and_builds_the_graph(checkout: Path) -> None:
    reader = FakeReader()

    first = build_graph(checkout, APP, [APP, WEB], reader, has_tests_folder)
    second = build_graph(checkout, APP, [APP, WEB], reader, has_tests_folder)

    root, sources, tests = reader.calls[0]
    assert root == checkout / "app"
    assert sources == ["pkg/mod.py", "pkg/use.py"]
    assert tests == ["only_tests/tests/test_x.py", "tests/test_mod.py"]

    nodes = {node.id: node for node in first.nodes}
    assert set(nodes) == {
        ".",
        "pkg",
        "pkg/mod.py",
        "pkg/use.py",
        "pkg/mod.py::C",
        "pkg/mod.py::C.m",
        "pkg/mod.py::f",
    }
    assert nodes["pkg/mod.py"].tests == ("tests/test_mod.py",)
    assert {(e.kind, e.source, e.target) for e in first.edges} == {
        ("contains", ".", "pkg"),
        ("contains", "pkg", "pkg/mod.py"),
        ("contains", "pkg", "pkg/use.py"),
        ("contains", "pkg/mod.py", "pkg/mod.py::C"),
        ("contains", "pkg/mod.py", "pkg/mod.py::f"),
        ("contains", "pkg/mod.py::C", "pkg/mod.py::C.m"),
        ("imports", "pkg/use.py", "pkg/mod.py"),
    }
    assert {(e.name, e.target) for e in first.entry_points} == {
        ("ok", "pkg/mod.py::f"),
        ("bad", ""),
    }
    assert dump(first) == dump(second)


def test_the_root_project_leaves_out_every_file_under_another_project(checkout: Path) -> None:
    reader = FakeReader()

    build_graph(checkout, ROOT, [ROOT, WEB], reader, has_tests_folder)

    _, sources, _ = reader.calls[0]
    assert "top.py" in sources
    assert not [path for path in sources if path.startswith("app/web/")]
