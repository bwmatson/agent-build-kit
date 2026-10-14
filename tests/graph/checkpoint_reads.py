"""Reading a unit's thread back through the real checkpointer, for the checkpoint tests."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from langchain_core.runnables import RunnableConfig

from agent_build_kit.graph.build import compile_graph
from agent_build_kit.graph.checkpointer import open_checkpointer
from tests.factories import unit


def thread_config() -> RunnableConfig:
    return {"configurable": {"thread_id": unit().id, "checkpoint_ns": ""}}


def read_back(db: Path) -> Any:
    """The graph's state snapshot for the unit's thread, read with the allowed list."""

    async def read() -> Any:
        async with open_checkpointer(db) as saver:
            return await compile_graph(saver).aget_state(thread_config())

    return asyncio.run(read())
