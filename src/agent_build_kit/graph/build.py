"""The compiled graph: every node named in docs/unit-graph.md."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph.state import CompiledStateGraph

from agent_build_kit.graph.state import Node, UnitRun

NodeWork = Callable[[UnitRun], Awaitable[dict[str, Any]]]


def compile_graph(
    saver: BaseCheckpointSaver, *, work: Mapping[Node, NodeWork] | None = None
) -> CompiledStateGraph:
    """`work` replaces a node's body, the seam nodes are tested alone through."""
    raise NotImplementedError
