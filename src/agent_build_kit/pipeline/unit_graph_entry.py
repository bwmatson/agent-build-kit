"""The one door `abk serve` reaches a unit's graph thread through.

The graph belongs to the worker package, so `serve` reads a thread through this typed seam
and the server, which composes the worker in, registers the worker's implementation of it."""

from __future__ import annotations

from typing import Protocol

from langgraph.checkpoint.base import BaseCheckpointSaver

from agent_build_kit.pipeline.unit_state import Position


class UnitGraph(Protocol):
    """What a reader of a unit's thread needs of the graph."""

    async def position(self, saver: BaseCheckpointSaver, unit_id: str) -> Position:
        """Read `unit_id`'s thread without running it."""
        ...

    async def clear_running_node(self, saver: BaseCheckpointSaver, unit_id: str) -> None:
        """Forget the start a killed node left in `unit_id`'s thread."""
        ...


_graph: UnitGraph | None = None


class UnitGraphNotRegistered(RuntimeError):
    """`registered_unit_graph` was called before any graph was registered."""


def register_unit_graph(graph: UnitGraph | None) -> UnitGraph | None:
    """Fill the entry with `graph` (None empties it); returns the one it replaced."""
    global _graph
    replaced, _graph = _graph, graph
    return replaced


def registered_unit_graph() -> UnitGraph:
    """The registered graph. `create_app` registers it, so code that reads a thread outside a
    served app (a test, a command) registers one first."""
    if _graph is None:
        raise UnitGraphNotRegistered("no unit graph is registered: register one first")
    return _graph
