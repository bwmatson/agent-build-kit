"""The code map's graph and its byte-stable JSON dump."""

import json

import pytest

from agent_build_kit.codemap.graph import (
    SCHEMA_VERSION,
    CodeMap,
    Edge,
    EntryPoint,
    Node,
    dump,
    load,
)

NODES = [
    Node(id=".", kind="directory", path="."),
    Node(id="src", kind="directory", path="src"),
    Node(id="src/a.py", kind="file", path="src/a.py", lines=9, doc="Module a.", tests=("t/a.py",)),
    Node(id="src/b.py", kind="file", path="src/b.py", lines=3, tests=()),
    Node(
        id="src/a.py::C",
        kind="class",
        path="src/a.py",
        lines=5,
        signature="class C(Base)",
        span=(2, 6),
    ),
    Node(
        id="src/a.py::C.m",
        kind="function",
        path="src/a.py",
        lines=2,
        signature="def m(self)",
        span=(4, 5),
    ),
    Node(
        id="src/a.py::f",
        kind="function",
        path="src/a.py",
        lines=1,
        signature="def f()",
        span=(8, 8),
    ),
]
EDGES = [
    Edge(kind="contains", source=".", target="src"),
    Edge(kind="contains", source="src", target="src/a.py"),
    Edge(kind="contains", source="src/a.py", target="src/a.py::C"),
    Edge(kind="imports", source="src/b.py", target="src/a.py"),
    Edge(kind="invokes", source="src/b.py", target="src/a.py::f"),
    Edge(kind="inherits", source="src/a.py::C", target="src/a.py::C"),
]
ENTRY_POINTS = [
    EntryPoint(kind="script", name="zed", path="pyproject.toml", line=4, target="src/a.py::f"),
    EntryPoint(kind="script", name="abe", path="pyproject.toml", line=3, detail="x"),
]


def graph(order: int) -> CodeMap:
    """The same graph with its nodes, edges and entry points in a different order."""
    pick = (lambda items: items) if order == 0 else (lambda items: list(reversed(items)))
    return CodeMap(
        project="svc",
        profile="python-uv",
        nodes=tuple(pick(NODES)),
        edges=tuple(pick(EDGES)),
        entry_points=tuple(pick(ENTRY_POINTS)),
    )


def test_a_dump_is_sorted_one_line_each_stable_and_loads_back_equal() -> None:
    text = dump(graph(0))
    document = json.loads(text)

    assert text.endswith("\n")
    assert dump(graph(1)) == text
    assert load(text) == graph(0)
    assert list(document) == [
        "format",
        "version",
        "project",
        "profile",
        "nodes",
        "edges",
        "entry_points",
    ]
    assert document["format"] == "abk-codemap"
    assert document["version"] == SCHEMA_VERSION

    ids = [node["id"] for node in document["nodes"]]
    assert ids == sorted(node.id for node in NODES)
    assert all(list(node) == sorted(node) for node in document["nodes"])
    by_id = {node["id"]: node for node in document["nodes"]}
    assert by_id["src/b.py"]["tests"] == []
    assert "tests" not in by_id["src/a.py::C"]
    assert "doc" not in by_id["src/b.py"]
    assert document["edges"] == sorted(document["edges"])
    assert len(document["edges"]) == len(EDGES)
    assert [entry["name"] for entry in document["entry_points"]] == ["abe", "zed"]

    entries = [line for line in text.splitlines() if line.startswith(('{"', '["'))]
    assert len(entries) == len(NODES) + len(EDGES) + len(ENTRY_POINTS), "one entry per line"


@pytest.mark.parametrize(
    ("header", "found"),
    [
        ('{"format":"abk-codemap","version":2,"project":"p","profile":"q"}', "2"),
        ('{"format":"other-thing","version":1,"project":"p","profile":"q"}', "other-thing"),
    ],
)
def test_a_dump_of_another_format_or_version_is_refused_naming_it(header: str, found: str) -> None:
    text = header[:-1] + ',\n"nodes":[],\n"edges":[],\n"entry_points":[]\n}\n'

    with pytest.raises(Exception) as refused:
        load(text)

    assert found in str(refused.value)
