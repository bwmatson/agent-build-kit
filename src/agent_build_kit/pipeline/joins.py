"""The rules a planner's join must satisfy (docs/architecture.md).

A join hands one unit's work to another, so a wrong one builds two things on a
branch nobody planned. Each rule is checked here against the store as the plan
was made, and a join that breaks one raises `JoinRefused` — the round is
refused, not repaired. Joins are applied one after another to a copy of that
state, so a second join sees the first: three units in a line become one.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.unit_store import StoredUnit
from agent_build_kit.pipeline.units import CLOSED, MERGED, PLANNED, SATISFIED, Join, Member, Unit
from agent_build_kit.pipeline.work_graph import TaskGroup

# A dependency in one of these waits on nothing any more.
FINISHED = (MERGED, SATISFIED, CLOSED)


class JoinRefused(ValueError):
    """A join breaks one of the rules."""


class JoinContext(Frozen):
    """What joins are checked against, besides the plan itself."""

    # Every unit the store holds.
    stored: tuple[StoredUnit, ...]
    # Every change's task groups, for repo, tier, flags and `Separate:`.
    catalog: dict[str, tuple[TaskGroup, ...]]
    # The `Needs:` lines of the change being planned, by group.
    needs: dict[int, tuple[tuple[str, int], ...]] = {}


def check_joins(
    joins: Sequence[Join],
    *,
    context: JoinContext,
    plan: Sequence[Unit],
    change: str | None,
    groups: Sequence[TaskGroup],
    built: set[int],
    ceiling: int,
) -> None:
    """Raise `JoinRefused` for the first join that breaks a rule.

    `change` is the change being planned, whose own planned units the plan
    replaces, so they are neither candidates nor dependents here.
    """
    replaced = {
        u.id
        for u in context.stored
        if change is not None and u.change == change and u.state == PLANNED
    }
    state = {u.id: u for u in context.stored if u.id not in replaced}
    plan_depends = {u.id: u.depends_on for u in plan}
    catalog = dict(context.catalog)
    if change is not None:
        catalog[change] = tuple(groups)
    claimed = {number for unit in plan for number in unit.groups}

    for join in joins:
        name = f"join onto {join.onto}"

        def refuse(why: str, name: str = name) -> JoinRefused:
            return JoinRefused(f"{name}: {why}")

        if join.onto in replaced or join.unit in replaced:
            raise refuse("it belongs to the change being planned, which the plan replaces")
        onto = state.get(join.onto)
        if onto is None:
            raise refuse("no such unit")
        if not isinstance(onto, StoredUnit) or not onto.unstarted:
            raise refuse("it has started, and only a unit that has not is joined to")

        if join.unit:
            taken = state.get(join.unit)
            if taken is None:
                raise refuse(f"no unit {join.unit}")
            if taken.id == onto.id:
                raise refuse("a unit is not joined to itself")
            if not taken.unstarted:
                raise refuse(f"{taken.id} has started, and only a unit that has not is joined")
            if (taken.repo, taken.tier) != (onto.repo, onto.tier):
                raise refuse(f"{taken.id} is in another repo or tier")
            if onto.id not in taken.depends_on:
                raise refuse(f"{taken.id} does not depend on {onto.id}, so they are not in a line")
            for dependency in taken.depends_on:
                other = state.get(dependency)
                if dependency != onto.id and (other is None or other.state not in FINISHED):
                    raise refuse(f"{taken.id} also waits on {dependency}, which is unfinished")
            others = [
                u.id for u in state.values() if onto.id in u.depends_on and u.id != taken.id
            ] + [uid for uid, deps in plan_depends.items() if onto.id in deps]
            members = taken.members()
            added = taken.estimated_lines
        else:
            if change is None or join.change != change:
                raise refuse(f"{join.change or 'the groups'} are not of the change being planned")
            if not join.groups:
                raise refuse("it names no groups")
            by_number = {g.number: g for g in groups}
            for number in join.groups:
                group = by_number.get(number)
                if group is None:
                    raise refuse(f"group {number} is not in {change}'s tasks.md")
                if number in built or number in claimed:
                    raise refuse(f"group {number} is already built or claimed by a unit")
                if (group.repo, group.tier) != (onto.repo, onto.tier):
                    raise refuse(f"group {number} is tagged [{group.repo}] [{group.tier}]")
                for need in context.needs.get(number, ()):
                    holder = next((u for u in state.values() if _holds(u, need)), None)
                    if holder is None or (holder.id != onto.id and holder.state not in FINISHED):
                        raise refuse(f"group {number} also waits on {need[0]} group {need[1]}")
            claimed |= set(join.groups)
            others = [u.id for u in state.values() if onto.id in u.depends_on]
            members = (Member(change=join.change, groups=join.groups),)
            added = join.estimated_lines
            taken = None

        if others:
            raise refuse(f"{', '.join(others)} already depends on {onto.id}, so it is not a line")

        involved = [*onto.members(), *members]
        _check_groups(involved, catalog, refuse)

        if onto.estimated_lines + added > ceiling:
            raise refuse(
                f"{onto.estimated_lines}+{added} changed lines is over the ceiling of {ceiling}"
            )

        state[onto.id] = onto.taking(members, estimated_lines=added)
        if taken is not None:
            del state[taken.id]
            for unit_id, unit in list(state.items()):
                if taken.id in unit.depends_on:
                    state[unit_id] = unit.model_copy(
                        update={"depends_on": _repointed(unit, taken, onto)}
                    )
            for unit_id, deps in plan_depends.items():
                if taken.id in deps:
                    plan_depends[unit_id] = tuple(
                        dict.fromkeys(onto.id if dep == taken.id else dep for dep in deps)
                    )


def _holds(unit: Unit, need: tuple[str, int]) -> bool:
    return any(m.change == need[0] and need[1] in m.groups for m in unit.members())


def _repointed(unit: Unit, taken: Unit, onto: Unit) -> tuple[str, ...]:
    return tuple(dict.fromkeys(onto.id if dep == taken.id else dep for dep in unit.depends_on))


def _check_groups(
    members: Sequence[Member], catalog: Mapping[str, Sequence[TaskGroup]], refuse
) -> None:
    """No group involved is flagged, or marked to be kept separate."""
    for member in members:
        known = {g.number: g for g in catalog.get(member.change, ())}
        for number in member.groups:
            group = known.get(number)
            if group is None:
                raise refuse(f"group {number} of {member.change} is not in its tasks.md")
            if group.flag:
                raise refuse(
                    f"{member.change} group {number} is flagged [{group.flag}], which keeps "
                    "the ordering rules it has and is never joined"
                )
            if group.separate:
                raise refuse(f"{member.change} group {number} is marked `Separate:`")
            if group.independent:
                raise refuse(f"{member.change} group {number} is marked `Independent:`")
