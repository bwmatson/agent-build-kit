"""`run_unit_graph` reaches a unit's graph thread through a handler a registration call fills, and
the graph's state types are defined in the core, so a core or orchestrator module imports no
worker module for either."""

from __future__ import annotations

import asyncio
import importlib
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from agent_build_kit.graph.checkpointer import open_checkpointer, unit_graphs_path
from agent_build_kit.pipeline.unit_graph_entry import (
    UnitGraphHandler,
    UnitGraphNotRegistered,
    register_unit_graph,
    run_unit_graph,
)


@pytest.fixture
def entry() -> Iterator[None]:
    """Leave the entry as it was found: another test may rely on the graph's registration."""
    before = register_unit_graph(None)
    yield
    register_unit_graph(before)


def call(tmp_path: Path, operation: str) -> Any:
    async def go() -> Any:
        async with open_checkpointer(unit_graphs_path(tmp_path)) as saver:
            return await run_unit_graph(operation, saver, "feature/1")

    return asyncio.run(go())


def test_a_call_with_nothing_registered_fails_saying_so(entry: None, tmp_path: Path) -> None:
    with pytest.raises(UnitGraphNotRegistered, match="register"):
        call(tmp_path, "position")


def test_a_call_runs_the_registered_handler_and_returns_its_answer(
    entry: None, tmp_path: Path
) -> None:
    seen: list[tuple[str, str]] = []

    async def handler(operation: str, saver: Any, unit_id: str) -> str:
        seen.append((operation, unit_id))
        return "answer"

    register_unit_graph(handler)

    assert call(tmp_path, "clear_running_node") == "answer"
    assert seen == [("clear_running_node", "feature/1")]


def test_registering_again_returns_the_handler_it_replaced(entry: None) -> None:
    async def first(operation: str, saver: Any, unit_id: str) -> None: ...

    async def second(operation: str, saver: Any, unit_id: str) -> None: ...

    handlers: list[UnitGraphHandler | None] = [register_unit_graph(first)]
    handlers.append(register_unit_graph(second))

    assert handlers == [None, first]


@pytest.mark.parametrize("name", ["Node", "UnitRun", "AgentSession", "SessionRole", "EventKind"])
def test_the_graph_state_types_are_defined_in_the_core(name: str) -> None:
    state = importlib.import_module("agent_build_kit.pipeline.unit_state")

    assert getattr(state, name).__module__ == "agent_build_kit.pipeline.unit_state"
