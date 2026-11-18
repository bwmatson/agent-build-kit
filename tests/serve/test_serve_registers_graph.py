"""`abk serve`'s application registers the worker's unit graph with the core's entry."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from pathlib import Path

import pytest

from agent_build_kit.graph.checkpointer import open_checkpointer, unit_graphs_path
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.unit_graph_entry import register_unit_graph, registered_unit_graph
from agent_build_kit.pipeline.unit_state import Position
from agent_build_kit.serve.server import create_app


@pytest.fixture
def empty_entry() -> Iterator[None]:
    """Start with no graph registered, and leave the entry as it was found."""
    before = register_unit_graph(None)
    yield
    register_unit_graph(before)


def test_creating_the_app_registers_the_graph_so_a_missing_thread_reads_as_no_state(
    empty_entry: None, inst: Installation, tmp_path: Path
) -> None:
    create_app(inst)

    async def go() -> Position:
        async with open_checkpointer(unit_graphs_path(tmp_path)) as saver:
            return await registered_unit_graph().position(saver, "feature/1")

    assert asyncio.run(go()).state is None
