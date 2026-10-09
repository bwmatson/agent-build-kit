"""Clearing a killed node's recorded start leaves the thread where it was and the tree as the
kill left it."""

from __future__ import annotations

import asyncio
from pathlib import Path

from agent_build_kit.graph.checkpointer import open_checkpointer, unit_graphs_path
from agent_build_kit.graph.state import Node
from agent_build_kit.graph.unit import clear_running_node
from tests.graph.test_resume_over_leftovers import UNIT, killed_in
from tests.graph_driver import position
from tests.leftovers_driver import LEFTOVER


def clear(tmp_path: Path) -> None:
    async def go() -> None:
        async with open_checkpointer(unit_graphs_path(tmp_path / "state")) as saver:
            await clear_running_node(saver, UNIT)

    asyncio.run(go())


def test_clearing_the_start_keeps_the_threads_place_and_the_leftovers(tmp_path: Path) -> None:
    habitat, _ = killed_in(tmp_path, "implement")
    before = position(tmp_path)
    assert before.state is not None and before.state.running_node == "implement"

    clear(tmp_path)

    after = position(tmp_path)
    assert after.state is not None
    assert after.state.running_node == ""
    assert after.next == before.next == (Node.IMPLEMENT,)
    assert after.state.session_id == before.state.session_id
    assert (habitat.tree / LEFTOVER).exists()


def test_clearing_a_thread_with_no_start_changes_nothing(tmp_path: Path) -> None:
    killed_in(tmp_path, "implement")
    clear(tmp_path)

    clear(tmp_path)

    state = position(tmp_path).state
    assert state is not None and state.running_node == ""
