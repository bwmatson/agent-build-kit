"""Building a project's code map from its files and its profile's reader."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path, PurePosixPath

from agent_build_kit.codemap.graph import CodeMap, CodeReader, Edge, Node
from agent_build_kit.config import ProjectConfig, owning_project
from agent_build_kit.pipeline.shell import git

# The map's own files, never read back into the map.
MAP_FILES = (".codemap.json", "CODEMAP.md")


def _files(
    checkout: Path, project: ProjectConfig, projects: list[ProjectConfig], reader: CodeReader
) -> list[str]:
    """The project's live files the reader reads, relative to the project, sorted."""
    root = checkout / project.path
    listed = git(root, "ls-files", "-z", "--cached", "--others", "--exclude-standard").stdout
    kept = []
    for path in sorted(set(listed.split("\0")) - {""}):
        owner = owning_project(projects, project.prefix + path)
        if (
            (root / path).is_file()
            and owner is not None
            and owner.path == project.path
            and Path(path).name not in MAP_FILES
            and path.endswith(reader.suffixes)
        ):
            kept.append(path)
    return kept


def build_graph(
    checkout: Path,
    project: ProjectConfig,
    projects: list[ProjectConfig],
    reader: CodeReader,
    is_test: Callable[[str], bool],
) -> CodeMap:
    """The project's graph: its live source files as read by `reader`, the directories that
    hold them, and only the edges and entry-point targets that land on a node."""
    files = _files(checkout, project, projects, reader)
    tests = [path for path in files if is_test(project.prefix + path)]
    test_set = set(tests)
    sources = [path for path in files if path not in test_set]
    reading = reader.read(checkout / project.path, sources, tests)

    nodes: dict[str, Node] = {}
    edges: set[tuple[str, str, str]] = set()
    for facts in reading.files:
        nodes[facts.path] = Node(
            id=facts.path,
            kind="file",
            path=facts.path,
            lines=facts.lines,
            doc=facts.doc,
            tests=tuple(sorted(facts.tests)),
        )
        for symbol in facts.symbols:
            node_id = f"{facts.path}::{symbol.name}"
            nodes[node_id] = Node(
                id=node_id,
                kind=symbol.kind,
                path=facts.path,
                lines=symbol.lines,
                doc=symbol.doc,
                signature=symbol.signature,
                span=symbol.span,
            )
            owner, dotted, _ = symbol.name.rpartition(".")
            parent = f"{facts.path}::{owner}" if dotted else facts.path
            edges.add(("contains", parent, node_id))
        child = facts.path
        folder = PurePosixPath(facts.path).parent
        while True:
            directory = str(folder)
            nodes.setdefault(directory, Node(id=directory, kind="directory", path=directory))
            edges.add(("contains", directory, child))
            if directory == ".":
                break
            child, folder = directory, folder.parent
    edges.update((edge.kind, edge.source, edge.target) for edge in reading.edges)

    return CodeMap(
        project=project.path,
        profile=project.profile,
        nodes=tuple(nodes.values()),
        edges=tuple(
            Edge(kind=kind, source=source, target=target)
            for kind, source, target in edges
            if source in nodes and target in nodes
        ),
        entry_points=tuple(
            entry if entry.target in nodes else entry.model_copy(update={"target": ""})
            for entry in reading.entry_points
        ),
    )
