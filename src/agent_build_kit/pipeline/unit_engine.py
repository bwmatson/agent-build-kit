"""The seam `build_unit` runs a unit through: the classic engine or the graph."""

from __future__ import annotations

from typing import Protocol

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import Unit


class UnitEngine(Protocol):
    name: str

    def build(self, inst: Installation, unit: Unit, *, store: UnitStore) -> bool:
        """Build one unit; False only when the tick should stop entirely."""
        ...


class ClassicEngine:
    """`UnitRunner`, as `build_unit` has always run it."""

    name = "classic"

    def build(self, inst: Installation, unit: Unit, *, store: UnitStore) -> bool:
        raise NotImplementedError


def select_engine(name: str) -> UnitEngine:
    """The engine registered under `name`."""
    raise NotImplementedError
