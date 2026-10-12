"""Cycles in the unit graph: find one, and drop the planner edges that would close one."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.unit_store import UNPLANNED, StoredUnit
from agent_build_kit.pipeline.units import CLOSED, MERGED, PLANNED, Unit


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


# Units whose work is done or abandoned: nothing waits on them, so they sit in no cycle.
FINISHED = (MERGED, CLOSED, UNPLANNED)


def path_between(edges: Mapping[str, Sequence[str]], start: str, goal: str) -> tuple[str, ...]:
    """A path from `start` to `goal` along `edges`, dependencies in stored order, or empty."""
    path = [start]
    iterators = [iter(edges.get(start, ()))]
    seen = {start}
    while iterators:
        if path[-1] == goal:
            return tuple(path)
        for dependency in iterators[-1]:
            if dependency not in seen:
                seen.add(dependency)
                path.append(dependency)
                iterators.append(iter(edges.get(dependency, ())))
                break
        else:
            iterators.pop()
            path.pop()
    return ()


def find_cycle(edges: Mapping[str, Sequence[str]]) -> tuple[str, ...]:
    """The first cycle of a graph from each id to the ids it depends on, as ids closing
    on the first (`A -> B -> A`), or empty. Deterministic: ids are visited in sorted order."""
    done: set[str] = set()
    for root in sorted(edges):
        if root in done:
            continue
        path = [root]
        on_path = {root}
        iterators = [iter(edges.get(root, ()))]
        while iterators:
            for dependency in iterators[-1]:
                if dependency in on_path:
                    return (*path[path.index(dependency) :], dependency)
                if dependency not in done:
                    path.append(dependency)
                    on_path.add(dependency)
                    iterators.append(iter(edges.get(dependency, ())))
                    break
            else:
                iterators.pop()
                done.add(path.pop())
                on_path = set(path)
    return ()


def drop_cycle_edges(
    plan_units: Sequence[Unit],
    stored_units: Sequence[StoredUnit],
    declared_needs: Mapping[str, Sequence[str]],
) -> CycleDrops:
    """Drop the plan's dependencies that would close a cycle with the units not finished.

    `declared_needs` maps a unit id to the unit ids its `Needs:` lines name. Stored
    dependencies and declared ones are fixed; the plan's are advisory and tried one at a
    time in the plan's order. A cycle of fixed edges alone leaves the plan as it is."""
    planning = {unit.change for unit in plan_units}
    graph: dict[str, list[str]] = {}
    for stored in stored_units:
        if stored.state in FINISHED or (stored.state == PLANNED and stored.change in planning):
            continue
        graph.setdefault(stored.id, []).extend(stored.depends_on)
    for unit_id, needed in declared_needs.items():
        graph.setdefault(unit_id, []).extend(n for n in needed if n not in graph.get(unit_id, ()))
    if cycle := find_cycle(graph):
        return CycleDrops(units=tuple(plan_units), cycle=cycle)

    kept: list[Unit] = []
    dropped: list[CycleEdge] = []
    for unit in plan_units:
        dependencies: list[str] = []
        for dependency in unit.depends_on:
            back = path_between(graph, dependency, unit.id)
            if back:
                dropped.append(
                    CycleEdge(unit=unit.id, dependency=dependency, cycle=(unit.id, *back))
                )
                continue
            dependencies.append(dependency)
            graph.setdefault(unit.id, []).append(dependency)
        kept.append(unit.model_copy(update={"depends_on": tuple(dependencies)}))
    return CycleDrops(units=tuple(kept), dropped=tuple(dropped))
