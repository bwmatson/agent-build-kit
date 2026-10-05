"""Moving the units in flight onto threads (docs/unit-graph.md, Moving the units in flight)."""

from __future__ import annotations

from langgraph.checkpoint.base import BaseCheckpointSaver

from agent_build_kit.pipeline.unit_store import UnitStore


async def convert_units_in_flight(saver: BaseCheckpointSaver, store: UnitStore) -> tuple[str, ...]:
    """Seed a thread for each stored unit that has no thread and something in
    flight, positioned at the node its stored step names; return their ids."""
    raise NotImplementedError
