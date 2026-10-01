"""The compiled graph: every node named in docs/unit-graph.md."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any, cast

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from agent_build_kit.graph.state import Node, UnitRun

NodeWork = Callable[[UnitRun], Awaitable[dict[str, Any]]]

# The skeleton's one path through the nodes; the routing between them is the
# build path's work.
ORDER = (
    Node.PREPARE,
    Node.TESTS,
    Node.IMPLEMENT,
    Node.CHECKS,
    Node.REVIEW,
    Node.TIER1,
    Node.VERIFY_BASE,
    Node.PUSH,
    Node.OPEN_PR,
    Node.AWAIT_REVIEW,
)


async def nothing(state: UnitRun) -> dict[str, Any]:
    return {}


def compile_graph(
    saver: BaseCheckpointSaver, *, work: Mapping[Node, NodeWork] | None = None
) -> CompiledStateGraph:
    """`work` replaces a node's body, the seam nodes are tested alone through."""
    work = work or {}
    builder = StateGraph(UnitRun)
    for node in Node:
        builder.add_node(node.value, cast("Any", work.get(node, nothing)))
    builder.add_edge(START, Node.PREPARE.value)
    for node, after in zip(ORDER, ORDER[1:], strict=False):
        builder.add_edge(node.value, after.value)
    builder.add_edge(ORDER[-1].value, END)
    return builder.compile(checkpointer=saver)
