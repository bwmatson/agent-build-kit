"""The code map's graph, its byte-stable JSON, and the seam a profile's reader fills."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from pydantic import field_validator

from agent_build_kit.model import Frozen

SCHEMA_VERSION = 1


class Node(Frozen):
    id: str
    kind: str
    path: str
    lines: int | None = None
    doc: str = ""
    signature: str = ""
    span: tuple[int, int] | None = None
    # A source file's test files; None for any other node, `()` meaning "none".
    tests: tuple[str, ...] | None = None


class Edge(Frozen):
    kind: str
    source: str
    target: str


class EntryPoint(Frozen):
    kind: str
    name: str
    path: str
    line: int
    detail: str = ""
    target: str = ""


class CodeMap(Frozen):
    project: str
    profile: str
    nodes: tuple[Node, ...] = ()
    edges: tuple[Edge, ...] = ()
    entry_points: tuple[EntryPoint, ...] = ()

    @field_validator("nodes")
    @classmethod
    def _sorted_nodes(cls, nodes: tuple[Node, ...]) -> tuple[Node, ...]:
        return tuple(sorted(nodes, key=lambda n: n.id))

    @field_validator("edges")
    @classmethod
    def _sorted_edges(cls, edges: tuple[Edge, ...]) -> tuple[Edge, ...]:
        return tuple(sorted(edges, key=lambda e: (e.kind, e.source, e.target)))

    @field_validator("entry_points")
    @classmethod
    def _sorted_entry_points(cls, entries: tuple[EntryPoint, ...]) -> tuple[EntryPoint, ...]:
        return tuple(sorted(entries, key=lambda e: (e.kind, e.name, e.path, e.line)))


class Symbol(Frozen):
    kind: str
    name: str
    span: tuple[int, int]
    lines: int
    signature: str
    doc: str = ""


class FileFacts(Frozen):
    path: str
    lines: int
    doc: str = ""
    symbols: tuple[Symbol, ...] = ()
    tests: tuple[str, ...] = ()


class Reading(Frozen):
    files: tuple[FileFacts, ...] = ()
    edges: tuple[Edge, ...] = ()
    entry_points: tuple[EntryPoint, ...] = ()
    problems: tuple[str, ...] = ()


class CodeReader(Protocol):
    suffixes: tuple[str, ...]

    def read(self, root: Path, sources: Sequence[str], tests: Sequence[str]) -> Reading: ...


FORMAT = "abk-codemap"


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _node_json(node: Node) -> str:
    fields: dict[str, object] = {"id": node.id, "kind": node.kind, "path": node.path}
    if node.lines is not None:
        fields["lines"] = node.lines
    if node.doc:
        fields["doc"] = node.doc
    if node.signature:
        fields["signature"] = node.signature
    if node.span is not None:
        fields["span"] = list(node.span)
    if node.tests is not None:
        fields["tests"] = list(node.tests)
    return _json(fields)


def _entry_json(entry: EntryPoint) -> str:
    fields: dict[str, object] = {
        "kind": entry.kind,
        "name": entry.name,
        "path": entry.path,
        "line": entry.line,
    }
    if entry.detail:
        fields["detail"] = entry.detail
    if entry.target:
        fields["target"] = entry.target
    return _json(fields)


def _section(name: str, lines: list[str], last: bool = False) -> str:
    body = ",\n".join(lines)
    closing = "]" if last else "],"
    return f'"{name}": [\n' + (body + "\n" if lines else "") + closing + "\n"


def dump(graph: CodeMap) -> str:
    """The graph as JSON: sorted, one node, edge or entry point per line, byte-stable."""
    nodes = [_node_json(node) for node in sorted(graph.nodes, key=lambda n: n.id)]
    edges = [
        _json([edge.kind, edge.source, edge.target])
        for edge in sorted(graph.edges, key=lambda e: (e.kind, e.source, e.target))
    ]
    entries = [
        _entry_json(entry)
        for entry in sorted(graph.entry_points, key=lambda e: (e.kind, e.name, e.path, e.line))
    ]
    header = (
        f'"format": {_json(FORMAT)},\n"version": {SCHEMA_VERSION},\n'
        f'"project": {_json(graph.project)},\n"profile": {_json(graph.profile)},\n'
    )
    return (
        "{\n"
        + header
        + _section("nodes", nodes)
        + _section("edges", edges)
        + _section("entry_points", entries, last=True)
        + "}\n"
    )


def load(text: str) -> CodeMap:
    """Read a dump back; a format or version other than this one is refused, naming it."""
    document = json.loads(text)
    if document.get("format") != FORMAT:
        raise ValueError(f"not a code map: format {document.get('format')!r}")
    if document.get("version") != SCHEMA_VERSION:
        raise ValueError(f"unsupported code map version {document.get('version')!r}")
    nodes = []
    for raw in document["nodes"]:
        fields = dict(raw)
        if "span" in fields:
            fields["span"] = tuple(fields["span"])
        if "tests" in fields:
            fields["tests"] = tuple(fields["tests"])
        nodes.append(Node(**fields))
    return CodeMap(
        project=document["project"],
        profile=document["profile"],
        nodes=tuple(nodes),
        edges=tuple(Edge(kind=k, source=s, target=t) for k, s, t in document["edges"]),
        entry_points=tuple(EntryPoint(**raw) for raw in document["entry_points"]),
    )
