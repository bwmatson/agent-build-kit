"""Cycles in the unit graph: find one, and drop the planner edges that would close one."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.unit_store import StoredUnit
from agent_build_kit.pipeline.units import Unit


class CycleEdge(Frozen):
    """A dependency of `unit` on `dependency` that would close `cycle`, which starts
    at `unit` and ends on it: dropped from a plan, or refused from a `Needs:` line."""

    unit: str
    dependency: str
    cycle: tuple[str, ...]


class CycleDrops(Frozen):
    """What `drop_cycle_edges` made of a plan: its units without the planner edges that
    would close a cycle, those edges, and a cycle of fixed edges alone (empty if none)."""

    units: tuple[Unit, ...]
    dropped: tuple[CycleEdge, ...] = ()
    cycle: tuple[str, ...] = ()


def find_cycle(edges: Mapping[str, Sequence[str]]) -> tuple[str, ...]:
    """The first cycle of a graph from each id to the ids it depends on, as ids closing
    on the first (`A -> B -> A`), or empty. Deterministic: ids are visited in sorted order."""
    raise NotImplementedError


def drop_cycle_edges(
    plan_units: Sequence[Unit],
    stored_units: Sequence[StoredUnit],
    declared_needs: Mapping[str, Sequence[str]],
) -> CycleDrops:
    """Drop the plan's dependencies that would close a cycle with the units not finished.

    `declared_needs` maps a unit id to the unit ids its `Needs:` lines name."""
    raise NotImplementedError
