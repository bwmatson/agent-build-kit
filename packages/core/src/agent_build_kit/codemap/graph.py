"""The code map's graph, its byte-stable JSON, and the seam a profile's reader fills."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

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


def dump(graph: CodeMap) -> str:
    raise NotImplementedError


def load(text: str) -> CodeMap:
    raise NotImplementedError
