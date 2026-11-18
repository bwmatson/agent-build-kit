"""`abk serve`'s server registers the worker's unit graph with the core's entry when it loads."""

from __future__ import annotations

import asyncio
import importlib
from pathlib import Path
from typing import Any

from agent_build_kit.graph.checkpointer import open_checkpointer, unit_graphs_path
from agent_build_kit.pipeline.unit_graph_entry import run_unit_graph


def test_the_servers_start_registers_the_graph_so_a_missing_thread_reads_as_no_state(
    tmp_path: Path,
) -> None:
    importlib.import_module("agent_build_kit.serve.server")

    async def go() -> Any:
        async with open_checkpointer(unit_graphs_path(tmp_path)) as saver:
            return await run_unit_graph("position", saver, "feature/1")

    assert asyncio.run(go()).state is None
