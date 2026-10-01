"""The SQLite checkpointer: where a unit's thread lives between ticks."""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from pathlib import Path

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

# The (module, name) of every type the state holds, the only ones a
# checkpoint may deserialise.
ALLOWED_MSGPACK_MODULES: tuple[tuple[str, str], ...] = ()


def unit_graphs_path(state_dir: Path) -> Path:
    """`<state_dir>/unit-graphs.sqlite`."""
    raise NotImplementedError


def open_checkpointer(path: Path) -> AbstractAsyncContextManager[AsyncSqliteSaver]:
    raise NotImplementedError
