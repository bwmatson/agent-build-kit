"""The seam `build_unit` runs a unit through: the classic engine or the graph."""

from __future__ import annotations

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

    A build starts the unit's thread, or resumes the one a killed or paused
    run left, and runs it to a wait or the end; the store moves as the nodes
    move it. Events and `abk requeue` resume the thread through
    `cli.pipeline.resume_thread`.
    """

    name = "graph"

    def build(self, inst: Installation, unit: Unit, *, store: UnitStore) -> bool:
        # Late: the CLI module imports this one.
        from agent_build_kit.cli import pipeline

        return pipeline.build_graph(inst, unit, store=store)


ENGINES: dict[str, UnitEngine] = {e.name: e for e in (ClassicEngine(), GraphEngine())}


def select_engine(name: str) -> UnitEngine:
    """The engine registered under `name`."""
    try:
        return ENGINES[name]
    except KeyError:
        raise ValueError(f"unknown engine {name!r}; one of {', '.join(ENGINES)}") from None
