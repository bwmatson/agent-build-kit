"""The compiled graph: every node named in docs/unit-graph.md."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any, cast

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from agent_build_kit.graph.nodes import ROUTES
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


# The nodes of the build path, which `compile_build_path` needs a body for each of.
BUILD_NODES = tuple(Node)


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


def compile_build_path(
    saver: BaseCheckpointSaver, work: Mapping[Node, NodeWork]
) -> CompiledStateGraph:
    """The build path: the nodes in `work`, joined by the edges of docs/unit-graph.md.

    A router's return value is checked against the nodes it may name when the
    graph compiles, so a misspelled edge fails here and not in the middle of a run.
    """
    builder = StateGraph(UnitRun)
    for node, body in work.items():
        builder.add_node(node.value, cast("Any", body))
    builder.add_edge(START, Node.PREPARE.value)
    for node, (router, targets) in ROUTES.items():
        builder.add_conditional_edges(
            node.value, router, {str(target): str(target) for target in targets}
        )
    for node in (Node.FAILED, Node.SATISFIED):
        builder.add_edge(node.value, END)
    return builder.compile(checkpointer=saver)
