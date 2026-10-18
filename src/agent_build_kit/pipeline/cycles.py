"""Cycles in the unit graph: find one, and drop the planner edges that would close one."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.unit_store import UNPLANNED, StoredUnit
from agent_build_kit.pipeline.units import CLOSED, MERGED, PLANNED, Unit, UnitState, waiting_on
from agent_build_kit.pipeline.work_graph import group_needs, names_own_change, validate_tasks


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
FINISHED = (MERGED, CLOSED, UNPLANNED, UnitState.RETIRED)


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
    time in the plan's order, whether or not the fixed edges hold a cycle. A cycle of fixed
    edges through one of the plan's units is returned and drops nothing."""
    planning = {unit.change for unit in plan_units}
    graph: dict[str, list[str]] = {}
    for stored in stored_units:
        if stored.state in FINISHED or (stored.state == PLANNED and stored.change in planning):
            continue
        graph.setdefault(stored.id, []).extend(stored.depends_on)
    for unit_id, needed in declared_needs.items():
        graph.setdefault(unit_id, []).extend(n for n in needed if n not in graph.get(unit_id, ()))
    # A cycle of fixed edges is this plan's only if it runs through one of its units; one
    # elsewhere in the store is left to the status, and guards nothing less.
    cycle = next(
        (
            (unit.id, *back)
            for unit in plan_units
            for dependency in graph.get(unit.id, ())
            if (back := path_between(graph, dependency, unit.id))
        ),
        (),
    )

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
    return CycleDrops(units=tuple(kept), dropped=tuple(dropped), cycle=cycle)


def deadlocks(units: Sequence[StoredUnit]) -> list[tuple[str, ...]]:
    """Each cycle of planned units that each wait on the next, once, from its smallest id
    (`A -> B -> A`): the edges are what `waiting_on` says stops a unit starting, so a unit
    that can start is in no cycle. Derived each time, never stored."""
    graph = {
        u.id: [parent.id for parent in waiting_on(u, units)] for u in units if u.state == PLANNED
    }
    found: list[tuple[str, ...]] = []
    while cycle := find_cycle(graph):
        members = cycle[:-1]
        start = members.index(min(members))
        found.append((*members[start:], *members[:start], members[start]))
        graph = {
            unit_id: [d for d in needed if d not in members]
            for unit_id, needed in graph.items()
            if unit_id not in members
        }
    return found


def needs_cycle(tasks_files: Sequence[Path]) -> tuple[tuple[str, int], ...]:
    """A cycle among `(change, group)` nodes made of the `Needs:` lines of the changes'
    tasks files and the order of each change's consecutive groups (an `Independent:`
    group has none), as nodes closing on the first, or empty. A `Needs:` on the change's
    own group adds no edge."""
    edges: dict[str, list[str]] = {}
    for path in tasks_files:
        change = path.parent.name.lower()
        groups, _ = validate_tasks(path)
        needs = group_needs(path)
        for before, group in zip([None, *groups], groups, strict=False):
            node = f"{change} group {group.number}"
            edges.setdefault(node, [])
            if before is not None and not group.independent:
                edges[node].append(f"{change} group {before.number}")
            edges[node].extend(
                f"{need.change} group {need.group}"
                for need in needs.get(group.number, ())
                if not names_own_change(need, path)
            )
    return tuple(
        (name, int(number))
        for node in find_cycle(edges)
        for name, number in [node.rsplit(" group ", 1)]
    )
