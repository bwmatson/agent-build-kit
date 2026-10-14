"""Reading a unit graph's thread back through the real checkpointer, for the checkpoint tests."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from langchain_core.runnables import RunnableConfig

from agent_build_kit.graph.build import compile_graph
from agent_build_kit.graph.checkpointer import open_checkpointer


def a_config(thread_id: str) -> RunnableConfig:
    return {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}


def read_back(db: Path, thread_id: str) -> Any:
    """The graph's state snapshot for `thread_id`, read with the allowed list."""

    async def read() -> Any:
        async with open_checkpointer(db) as saver:
            return await compile_graph(saver).aget_state(a_config(thread_id))

    return asyncio.run(read())


def task_names(db: Path, thread_id: str) -> dict[str, str]:
    """The node each task of the thread ran, by the task id the writes table keeps."""

    async def read() -> dict[str, str]:
        async with open_checkpointer(db) as saver:
            history = compile_graph(saver).aget_state_history(a_config(thread_id))
            return {task.id: task.name async for snapshot in history for task in snapshot.tasks}

    return asyncio.run(read())
