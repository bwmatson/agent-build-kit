"""The checkpointer database is carried once from the state directory to the local directory,
through SQLite's backup interface (spec: planning-local-directory)."""

from __future__ import annotations

import asyncio
from pathlib import Path

from langgraph.checkpoint.base import empty_checkpoint

from agent_build_kit.graph.checkpointer import open_checkpointer, unit_graphs_path


def put_thread(db: Path, thread_id: str, *, state_dir: Path | None = None) -> None:
    async def put() -> None:
        async with open_checkpointer(db, state_dir=state_dir) as saver:
            config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}
            await saver.aput(config, empty_checkpoint(), {}, {})

    asyncio.run(put())


def threads_in(db: Path, *, state_dir: Path | None = None) -> set[str]:
    async def read() -> set[str]:
        async with open_checkpointer(db, state_dir=state_dir) as saver:
            return {found.config["configurable"]["thread_id"] async for found in saver.alist(None)}

    return asyncio.run(read())


def old_database(state: Path) -> Path:
    """A database in `state` holding one thread, closed cleanly."""
    old = unit_graphs_path(state)
    put_thread(old, "unit-1")
    for sidecar in old.parent.glob(f"{old.name}-*"):
        sidecar.unlink()
    return old


def test_an_existing_database_is_copied_once_and_only_when_there_is_one_to_copy(
    tmp_path: Path,
) -> None:
    state, local = tmp_path / "state", tmp_path / "local"
    old = old_database(state)
    before = old.read_bytes()
    new = unit_graphs_path(local)

    assert threads_in(new, state_dir=state) == {"unit-1"}
    assert old.read_bytes() == before

    put_thread(new, "unit-2", state_dir=state)
    assert threads_in(new, state_dir=state) == {"unit-1", "unit-2"}
    assert threads_in(old) == {"unit-1"}

    # With no old file, only the new database is created.
    bare_state, bare_local = tmp_path / "bare-state", tmp_path / "bare-local"
    bare_state.mkdir()
    assert threads_in(unit_graphs_path(bare_local), state_dir=bare_state) == set()
    assert list(bare_state.iterdir()) == []
    assert unit_graphs_path(bare_local).exists()

    # With equal directories, nothing is copied: the one database is the one opened.
    assert threads_in(old, state_dir=state) == {"unit-1"}
    assert [p.name for p in state.iterdir() if not p.name.endswith(("-wal", "-shm"))] == [old.name]
