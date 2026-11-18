"""The one door `abk serve` reaches a unit's graph thread through.

The graph belongs to the worker package, so `serve` does not import it: the worker's
`graph/unit.py` registers a handler here, and `run_unit_graph` calls it."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver

UnitGraphHandler = Callable[[str, BaseCheckpointSaver, str], Awaitable[Any]]

_handler: UnitGraphHandler | None = None


class UnitGraphNotRegistered(RuntimeError):
    """`run_unit_graph` was called before any handler was registered."""


def register_unit_graph(handler: UnitGraphHandler | None) -> UnitGraphHandler | None:
    """Fill the entry with `handler` (None empties it); returns the one it replaced."""
    global _handler
    replaced, _handler = _handler, handler
    return replaced


async def run_unit_graph(operation: str, saver: BaseCheckpointSaver, unit_id: str) -> Any:
    """Run `operation` (`position` or `clear_running_node`) on `unit_id`'s thread through the
    registered handler."""
    if _handler is None:
        raise UnitGraphNotRegistered("no unit graph is registered: register one first")
    return await _handler(operation, saver, unit_id)
