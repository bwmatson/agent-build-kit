"""The SQLite checkpointer: where a unit's thread lives between ticks."""

from __future__ import annotations

import sqlite3
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING

import aiosqlite
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from agent_build_kit.pipeline.file_lock import atomic_write_bytes, file_lock

if TYPE_CHECKING:
    from agent_build_kit.installation import Installation

# The (module, name) of every type the state holds, the only ones a
# checkpoint may deserialise.
ALLOWED_MSGPACK_MODULES: tuple[tuple[str, str], ...] = (
    ("agent_build_kit.graph.state", "AgentSession"),
    ("agent_build_kit.graph.state", "EventKind"),
    ("agent_build_kit.graph.state", "Node"),
    ("agent_build_kit.graph.state", "ResumeEvent"),
    ("agent_build_kit.graph.state", "SessionRole"),
    ("agent_build_kit.graph.state", "UnitRun"),
    ("agent_build_kit.graph.state", "Verdict"),
    ("agent_build_kit.pipeline.stack_runner", "Restacked"),
    ("agent_build_kit.pipeline.stack_runner", "RunStatus"),
    ("agent_build_kit.pipeline.stack_runner", "UnitOutcome"),
    ("agent_build_kit.pipeline.unit_store", "FeedbackSource"),
    ("agent_build_kit.pipeline.unit_store", "RequeueReason"),
    ("agent_build_kit.pipeline.unit_store", "ReworkKind"),
)


def unit_graphs_path(local_dir: Path) -> Path:
    """`<local_dir>/unit-graphs.sqlite`."""
    return local_dir / "unit-graphs.sqlite"


@asynccontextmanager
async def open_checkpointer(
    path: Path, *, state_dir: Path | None = None
) -> AsyncIterator[AsyncSqliteSaver]:
    """The saver over `path`, in WAL, deserialising only the allowlisted types. A database in
    `state_dir` is copied to `path` once, when `path` holds none."""
    if state_dir is not None:
        carry_database(path, state_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(path) as conn:
        await conn.execute("PRAGMA journal_mode=WAL")
        serde = JsonPlusSerializer(allowed_msgpack_modules=list(ALLOWED_MSGPACK_MODULES))
        yield AsyncSqliteSaver(conn, serde=serde)


def open_unit_graphs(inst: Installation) -> AbstractAsyncContextManager[AsyncSqliteSaver]:
    """The saver over the installation's unit graphs, carrying an old database over first."""
    return open_checkpointer(unit_graphs_path(inst.local_dir), state_dir=inst.state_dir)


def carried_unit_graphs(inst: Installation) -> Path:
    """The path of the installation's unit graphs, after an old database has been carried over,
    for a reader that opens the file itself."""
    path = unit_graphs_path(inst.local_dir)
    carry_database(path, inst.state_dir)
    return path


def carry_database(path: Path, state_dir: Path) -> None:
    """Copy the database in `state_dir` to `path` once, when `path` holds none. Two processes
    opening for the first time take turns, and the second finds the copy made."""
    old = unit_graphs_path(state_dir)
    if old == path or not old.exists() or path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with file_lock(path.with_name(path.name + ".carry.lock")):
        if not path.exists():
            _carry(old, path)


def _carry(old: Path, new: Path) -> None:
    """Copy the database at `old` to `new` through SQLite's backup interface, which gives a
    consistent copy with the WAL applied and leaves `old` as it was."""
    source = sqlite3.connect(f"file:{old}?mode=ro", uri=True)
    copy = sqlite3.connect(":memory:")
    try:
        source.backup(copy)
        atomic_write_bytes(new, copy.serialize())
    finally:
        copy.close()
        source.close()
