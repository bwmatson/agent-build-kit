"""`registered_unit_graph` reaches a unit's graph thread through an object a registration call
fills, and the graph's state types are defined in the core, so a core or orchestrator module
imports no worker module for either."""

from __future__ import annotations

import asyncio
import importlib
from collections.abc import Iterator
from typing import Any

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from agent_build_kit.pipeline.unit_graph_entry import (
    UnitGraph,
    UnitGraphNotRegistered,
    register_unit_graph,
    registered_unit_graph,
)
from agent_build_kit.pipeline.unit_state import Position


@pytest.fixture
def entry() -> Iterator[None]:
    """Leave the entry as it was found: another test may rely on the graph's registration."""
    before = register_unit_graph(None)
    yield
    register_unit_graph(before)


class FakeGraph:
    """Satisfies `UnitGraph`, and records the calls that reach it."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def position(self, saver: Any, unit_id: str) -> Position:
        self.calls.append(("position", unit_id))
        return Position()

    async def clear_running_node(self, saver: Any, unit_id: str) -> None:
        self.calls.append(("clear_running_node", unit_id))


def test_asking_for_the_graph_with_nothing_registered_fails_saying_so(entry: None) -> None:
    with pytest.raises(UnitGraphNotRegistered, match="register"):
        registered_unit_graph()


def test_each_method_of_the_registered_graph_is_reached(entry: None) -> None:
    graph = FakeGraph()
    register_unit_graph(graph)
    saver = InMemorySaver()

    async def go() -> Position:
        found = await registered_unit_graph().position(saver, "feature/1")
        await registered_unit_graph().clear_running_node(saver, "feature/2")
        return found

    found = asyncio.run(go())

    assert found == Position()
    assert graph.calls == [("position", "feature/1"), ("clear_running_node", "feature/2")]


def test_registering_again_returns_the_graph_it_replaced(entry: None) -> None:
    first: UnitGraph = FakeGraph()
    second: UnitGraph = FakeGraph()

    replaced = [register_unit_graph(first), register_unit_graph(second)]

    assert replaced == [None, first]


@pytest.mark.parametrize(
    "name", ["Node", "UnitRun", "AgentSession", "SessionRole", "EventKind", "Position"]
)
def test_the_graph_state_types_are_defined_in_the_core(name: str) -> None:
    state = importlib.import_module("agent_build_kit.pipeline.unit_state")

    assert getattr(state, name).__module__ == "agent_build_kit.pipeline.unit_state"
