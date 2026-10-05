"""The SQLite checkpointer: where a unit's thread lives between ticks."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import aiosqlite
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

# The (module, name) of every type the state holds, the only ones a
# checkpoint may deserialise.
ALLOWED_MSGPACK_MODULES: tuple[tuple[str, str], ...] = (
    ("agent_build_kit.graph.state", "EventKind"),
    ("agent_build_kit.graph.state", "ResumeEvent"),
    ("agent_build_kit.graph.state", "ReviewRound"),
    ("agent_build_kit.graph.state", "UnitRun"),
    ("agent_build_kit.graph.state", "Verdict"),
    ("agent_build_kit.pipeline.stack_runner", "EarlierAnswer"),
    ("agent_build_kit.pipeline.stack_runner", "Finding"),
    ("agent_build_kit.pipeline.stack_runner", "FollowUp"),
    ("agent_build_kit.pipeline.stack_runner", "Restacked"),
    ("agent_build_kit.pipeline.stack_runner", "RunStatus"),
)


def unit_graphs_path(state_dir: Path) -> Path:
    """`<state_dir>/unit-graphs.sqlite`."""
    return state_dir / "unit-graphs.sqlite"


@asynccontextmanager
async def open_checkpointer(path: Path) -> AsyncIterator[AsyncSqliteSaver]:
    """The saver over `path`, in WAL, deserialising only the allowlisted types."""
    path.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(path) as conn:
        await conn.execute("PRAGMA journal_mode=WAL")
        serde = JsonPlusSerializer(allowed_msgpack_modules=list(ALLOWED_MSGPACK_MODULES))
        yield AsyncSqliteSaver(conn, serde=serde)
