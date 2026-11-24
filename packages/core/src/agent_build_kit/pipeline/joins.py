"""The rules a planner's join must satisfy (docs/architecture.md).

A join hands one unit's work to another, so a wrong one builds two things on a
branch nobody planned. Each rule is checked here against the store as the plan
was made, and a join that breaks one raises `JoinRefused` — the round is
refused, not repaired. Joins are applied one after another to a copy of that
state, so a second join sees the first: three units in a line become one.
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Mapping, Sequence

from agent_build_kit.config import active, review_ceiling
from agent_build_kit.model import Frozen, TestTier
from agent_build_kit.pipeline.unit_size import (
    Calibration,
    Kind,
    applied,
    calibrated,
    kind_of,
    largest_raw,
)
from agent_build_kit.pipeline.unit_store import StoredUnit
from agent_build_kit.pipeline.units import (
    FINISHED_STATES,
    PLANNED,
    Join,
    Member,
    Unit,
    current_dependencies,
    direct_dependencies,
    repointed,
)
from agent_build_kit.pipeline.verdict import REVIEW_TIERS, ReviewTier
from agent_build_kit.pipeline.work_graph import TaskGroup


class JoinRefused(ValueError):
    """A join breaks one of the rules."""


def _held_text(side: str, onto: str, onto_held: bool) -> str:
    held, free = (onto, side) if onto_held else (side, onto)
    return (
        f"{held} is held by someone outside the kit and {free} is not, and a unit carries "
        "held groups or none"
    )


class JoinContext(Frozen):
    """What joins are checked against, besides the plan itself."""

    # Every unit the store holds.
    stored: tuple[StoredUnit, ...]
    # Every change's task groups, for repo, tier, flags and `Separate:`.
    catalog: dict[str, tuple[TaskGroup, ...]]
    # The `Needs:` lines of the change being planned, by group.
    needs: dict[int, tuple[tuple[str, int], ...]] = {}
    # The stored units whose groups are all held by someone outside the kit (`held_units`).
    external_units: frozenset[str] = frozenset()


def check_joins(
    joins: Sequence[Join],
    *,
    context: JoinContext,
    plan: Sequence[Unit],
    change: str | None,
    groups: Sequence[TaskGroup],
    built: set[int],
    floor: Callable[[TaskGroup, str], str],
    calibrations: Mapping[Kind, Calibration] | None = None,
    external: Collection[int] = (),
) -> None:
    """Raise `JoinRefused` for the first join that breaks a rule.

    A join is also refused when its two sides differ in being held by someone outside the kit:
    `external` is the held groups of `change`, `context.external_units` the held stored units.

    A join is held to the ceiling of the higher review tier of its two sides (a unit with none
    counting as `full`, a group at its `floor(group, repo)`). A join is also refused when its
    two sides disagree on `full`: a join leaves no unit holding a floor-`full` group or a
    `full` unit beside lower work. A unit with no recorded tier counts as `full`, as it does
    for sizing.

    `change` is the change being planned, whose own planned units the plan
    replaces, so they are neither candidates nor dependents here.
    """
    replaced = {
        u.id
        for u in context.stored
        if change is not None and u.change == change and u.state == PLANNED
    }
    state = {u.id: u for u in context.stored if u.id not in replaced}
    planned = {u.id: u for u in plan}

    def direct(unit: Unit) -> tuple[str, ...]:
        # Read through the units a replan replaced, then without a dependency another reaches.
        graph = [*state.values(), *planned.values()]
        resolved = unit.model_copy(update={"depends_on": current_dependencies(unit, graph)})
        return direct_dependencies(resolved, graph)

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
        onto_tier = onto.review_tier or "full"
        onto_held = onto.id in context.external_units

        if join.unit:
            taken = state.get(join.unit)
            if taken is None:
                raise refuse(f"no unit {join.unit}")
            if taken.id == onto.id:
                raise refuse("a unit is not joined to itself")
            if not taken.unstarted:
                raise refuse(f"{taken.id} has started, and only a unit that has not is joined")
            if (taken.id in context.external_units) != onto_held:
                raise refuse(_held_text(taken.id, onto.id, onto_held))
            if taken.repo != onto.repo or _needs_stack(taken.tier) != _needs_stack(onto.tier):
                raise refuse(f"{taken.id} is in another repo or tier")
            if taken.project != onto.project:
                raise refuse(f"{taken.id} is in another project")
            if taken.split != onto.split:
                raise refuse(
                    f"{taken.id} is in e2e-test split {taken.split!r}, not in {onto.id}'s "
                    f"({onto.split!r})"
                )
            if onto.id not in direct(taken):
                raise refuse(f"{taken.id} does not depend on {onto.id}, so they are not in a line")
            for dependency in direct(taken):
                other = state.get(dependency)
                if dependency != onto.id and (other is None or other.state not in FINISHED_STATES):
                    raise refuse(f"{taken.id} also waits on {dependency}, which is unfinished")
            others = [
                u.id
                for u in [*state.values(), *planned.values()]
                if onto.id in direct(u) and u.id != taken.id
            ]
            members = taken.members()
            added = taken.estimated_lines
            added_kinds = [taken.tier]
            added_tier = taken.review_tier or "full"
            sides = [(onto.id, onto_tier), (taken.id, added_tier)]
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
                if (number in external) != onto_held:
                    raise refuse(_held_text(f"group {number}", onto.id, onto_held))
                if group.repo != onto.repo or _needs_stack(group.tier) != _needs_stack(onto.tier):
                    raise refuse(f"group {number} is tagged [{group.repo}] [{group.tier}]")
                if group.project != onto.project:
                    raise refuse(
                        f"group {number} is in project {group.project!r}, not in {onto.id}'s"
                    )
                if group.split != onto.split:
                    raise refuse(
                        f"group {number} is in e2e-test split {group.split!r}, not in "
                        f"{onto.id}'s ({onto.split!r})"
                    )
                for need in context.needs.get(number, ()):
                    holder = next((u for u in state.values() if _holds(u, need)), None)
                    if holder is None or (
                        holder.id != onto.id and holder.state not in FINISHED_STATES
                    ):
                        raise refuse(f"group {number} also waits on {need[0]} group {need[1]}")
            claimed |= set(join.groups)
            added_kinds = [by_number[number].tier for number in join.groups]
            floors = {n: floor(by_number[n], onto.repo) for n in join.groups}
            added_tier = max(floors.values(), key=REVIEW_TIERS.index)
            sides = [(f"group {n}", tier) for n, tier in floors.items()]
            sides.append((onto.id, onto_tier))
            others = [u.id for u in state.values() if onto.id in direct(u)]
            members = (Member(change=join.change, groups=join.groups),)
            added = join.estimated_lines
            taken = None

        if others:
            raise refuse(f"{', '.join(others)} already depends on {onto.id}, so it is not a line")

        full = [side for side, tier in sides if tier == "full"]
        lower = [side for side, tier in sides if tier != "full"]
        if full and lower:
            raise refuse(mixed_floors_text(full, lower))

        involved = [*onto.members(), *members]
        _check_groups(involved, catalog, refuse)

        ratio = applied(calibrations, kind_of(onto))
        workspace = active()
        tier = max(onto_tier, added_tier, key=REVIEW_TIERS.index)
        limit = review_ceiling(workspace.repos.get(onto.repo), workspace, ReviewTier(tier))
        name = f"{tier} ceiling"
        if calibrated(onto.estimated_lines + added, ratio.ratio) > limit:
            raise refuse(
                f"{onto.estimated_lines}+{added} changed lines"
                + (
                    f" times {ratio.ratio:.2f} (from {ratio.samples} samples) is "
                    f"{calibrated(onto.estimated_lines + added, ratio.ratio)},"
                    if ratio.ratio != 1.0
                    else ""
                )
                + f" over the {name} of {limit}"
                + (
                    f" (the largest raw estimate for {kind_of(onto).label} is "
                    f"{largest_raw(limit, ratio.ratio)})"
                    if ratio.ratio != 1.0
                    else ""
                )
            )

        joined = onto.taking(members, estimated_lines=added, kinds=added_kinds)
        state[onto.id] = joined.model_copy(update={"review_tier": tier})
        if taken is not None:
            del state[taken.id]
            moved = repointed({**state, **planned}, taken.id, onto.id)
            for uid, unit in moved.items():
                update = {"depends_on": unit.depends_on}
                if uid in state:
                    state[uid] = state[uid].model_copy(update=update)
                else:
                    planned[uid] = planned[uid].model_copy(update=update)


def group_names(numbers: Sequence[int]) -> list[str]:
    """The groups as a refusal names them."""
    return [f"group {n}" for n in numbers]


def mixed_floors_text(full: Sequence[str], lower: Sequence[str]) -> str:
    """The refusal for work that expects full review sharing a unit with work that does not."""
    return (
        f"{' and '.join(full)}, whose floor is `full`, with {' and '.join(lower)}, whose floor "
        "is lower — work that needs full review is a unit of its own or with others that do"
    )


def _needs_stack(kind: TestTier) -> bool:
    """Whether `kind` needs the live stack: a join pairs two kinds that both do, or neither."""
    return kind == TestTier.E2E_TEST


def _holds(unit: Unit, need: tuple[str, int]) -> bool:
    return any(m.change == need[0] and need[1] in m.groups for m in unit.members())


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
            if group.tier == TestTier.E2E_TEST:
                raise refuse(
                    f"{member.change} group {number} is [{TestTier.E2E_TEST}], which always "
                    "has a unit of its own"
                )
            if group.flag:
                raise refuse(
                    f"{member.change} group {number} is flagged [{group.flag}], which keeps "
                    "the ordering rules it has and is never joined"
                )
            if group.separate:
                raise refuse(f"{member.change} group {number} is marked `Separate:`")
            if group.independent:
                raise refuse(f"{member.change} group {number} is marked `Independent:`")
