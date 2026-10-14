"""A value a node writes that the checkpoint would block is reported with the node that wrote it."""

from __future__ import annotations

import asyncio
from pathlib import Path

from agent_build_kit.graph.build import compile_graph
from agent_build_kit.graph.checkpointer import open_checkpointer, unit_graphs_path
from agent_build_kit.pipeline.units import PLANNED
from tests.checkpoint_types import blocked_in, node_updates
from tests.factories import unit
from tests.graph.checkpoint_reads import a_config
from tests.graph.test_hold_causes import fresh, upstream_went_back

THREAD = unit().id


def write_an_enum_as_a_node(db: Path) -> str:
    """Store `hold_state` as the enum under a task a snapshot names; that task's node."""

    async def write() -> str:
        async with open_checkpointer(db) as saver:
            history = compile_graph(saver).aget_state_history(a_config(THREAD))
            snapshot = [s async for s in history if s.tasks][0]
            task = snapshot.tasks[0]
            await saver.aput_writes(snapshot.config, [("hold_state", PLANNED)], task.id)
            return task.name

    return asyncio.run(write())


def test_a_node_writing_an_enum_off_the_list_is_reported_with_its_name_and_the_type(
    tmp_path: Path,
) -> None:
    upstream_went_back(tmp_path, fresh(tmp_path))
    db = unit_graphs_path(tmp_path / "state")

    node = write_an_enum_as_a_node(db)

    assert f"{node}.hold_state: agent_build_kit.pipeline.units.UnitState" in blocked_in(
        node_updates(db, THREAD)
    )
