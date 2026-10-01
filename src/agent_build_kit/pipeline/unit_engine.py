"""The seam `build_unit` runs a unit through: the classic engine or the graph."""

from __future__ import annotations

import asyncio
from typing import Protocol

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import Unit


class UnitEngine(Protocol):
    name: str

    def build(self, inst: Installation, unit: Unit, *, store: UnitStore) -> bool:
        """Build one unit; False only when the tick should stop entirely.

        Nothing in here may raise: the tick loop reads the result with
        `future.result()`, so an error that escapes ends the whole tick, not
        one unit. Log it and return True.
        """
        ...


class ClassicEngine:
    """`UnitRunner`, as `build_unit` has always run it."""

    name = "classic"

    def build(self, inst: Installation, unit: Unit, *, store: UnitStore) -> bool:
        # Late: the CLI module imports this one.
        from agent_build_kit.cli import pipeline

        return pipeline.build_classic(inst, unit, store=store)


class GraphEngine:
    """One LangGraph thread per unit, named by its id.

    The nodes do no step's work yet: a build only starts the thread and the
    unit stays `planned`.
    """

    name = "graph"

    def build(self, inst: Installation, unit: Unit, *, store: UnitStore) -> bool:
        # Late: the CLI module imports this one.
        from agent_build_kit.cli.pipeline import log

        try:
            asyncio.run(self._run(inst, unit))
        except Exception as error:
            log(f"{unit.id}: the graph engine failed: {type(error).__name__}: {error}")
            return True
        log(f"{unit.id}: the graph engine ran no step; the unit stays {unit.state}")
        return True

    async def _run(self, inst: Installation, unit: Unit) -> None:
        from agent_build_kit.graph.build import compile_graph
        from agent_build_kit.graph.checkpointer import open_checkpointer, unit_graphs_path
        from agent_build_kit.graph.run import run_thread
        from agent_build_kit.graph.state import UnitRun

        run = UnitRun(unit_id=unit.id, change=unit.change, groups=tuple(unit.groups))
        async with open_checkpointer(unit_graphs_path(inst.state_dir)) as saver:
            graph = compile_graph(saver)
            await run_thread(graph, run, unit.id)


ENGINES: dict[str, UnitEngine] = {e.name: e for e in (ClassicEngine(), GraphEngine())}


def select_engine(name: str) -> UnitEngine:
    """The engine registered under `name`."""
    try:
        return ENGINES[name]
    except KeyError:
        raise ValueError(f"unknown engine {name!r}; one of {', '.join(ENGINES)}") from None
