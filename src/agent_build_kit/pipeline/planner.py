"""The planner pass: propose the unit graph, then verify it.

Once a round, an LLM reads every change in flight and the work already open,
and returns the whole graph as JSON (docs/architecture.md).
Nothing is cached: the graph is re-derived each round rather than kept as a
file that drifts from reality.

An LLM is used because the parts that matter can't be read off `tasks.md`.
Dependencies *between* changes, edges implied by two groups touching the same
files, and whether two groups can safely run at once are judgements, not
lookups. The ordering inside a change, and the repo and tier tags, come from
the change itself — those are checked mechanically by `work_graph --validate`
long before this runs.

Because its output schedules real work in real repos, **validation refuses
rather than repairs**. A guessed repo builds in the wrong place; a dropped
dependency builds against code that doesn't exist yet. A malformed graph
stops the round, which costs one round — far less than either of those.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping, Sequence

from agent_build_kit import runtimes
from agent_build_kit.compat_names import Place, new_spelling, old_spelling
from agent_build_kit.config import REST_SPLIT, active
from agent_build_kit.model import Frozen, TestTier
from agent_build_kit.pipeline.call_record import recorded
from agent_build_kit.pipeline.joins import JoinContext, JoinRefused, check_joins
from agent_build_kit.pipeline.unit_size import (
    Calibration,
    Kind,
    applied,
    calibrated,
    largest_raw,
)
from agent_build_kit.pipeline.unit_store import StoredUnit, UnitStore
from agent_build_kit.pipeline.units import Join, Priority, Unit, UnitState, waiting_on_me
from agent_build_kit.pipeline.vocabulary import OverheadNode
from agent_build_kit.pipeline.work_graph import (
    GROUP_HEADING,
    GROUP_NUMBER,
    TEST_KIND_TAGS,
    TaskGroup,
    known_repos,
    split_repo_tag,
)
from agent_build_kit.runtimes import AgentRequest
from agent_build_kit.runtimes.base import AgentRuntime, PromptTooLarge, check_prompt_size

RunClaude = Callable[[str], str]

# The old tag of each kind, which the prompt says a group may still carry.
OLD_UNIT_TEST, OLD_E2E = old_spelling(TestTier.UNIT_TEST), old_spelling(TestTier.E2E_TEST)

JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)


class PlannerError(Exception):
    """The proposed graph can't be trusted, so the round stops here.

    `units` holds the ids the planner returned when the refusal came after reading them.
    """

    units: tuple[str, ...] = ()


class GroupTooLarge(PlannerError):
    """One task group is estimated over the ceiling on its own. No grouping
    fixes that — the change's tasks need splitting — so asking again cannot
    help."""


class InFlight(Frozen):
    """A unit that already exists, as context for placing new work."""

    id: str
    repo: str
    branch: str
    state: str


class Plan(Frozen):
    """A verified answer: the change's own units, and the joins to apply."""

    units: tuple[Unit, ...]
    joins: tuple[Join, ...] = ()


def parse_graph(
    output: str,
    *,
    groups: list[TaskGroup] | None = None,
    built: set[int] | None = None,
    known: set[str] | None = None,
) -> list[Unit]:
    """Read and verify a proposed graph, or raise `PlannerError`."""
    return list(parse_plan(output, groups=groups, built=built, known=known).units)


def parse_plan(
    output: str,
    *,
    groups: list[TaskGroup] | None = None,
    built: set[int] | None = None,
    known: set[str] | None = None,
    change: str | None = None,
    context: JoinContext | None = None,
    calibrations: Mapping[Kind, Calibration] | None = None,
) -> Plan:
    """Read and verify a proposed graph and its joins, or raise `PlannerError`.

    Joins are checked against `context`; without one, none may be proposed.
    """
    match = JSON_BLOCK.search(output)
    if not match:
        raise PlannerError("no JSON object in the planner's output")

    try:
        payload = json.loads(match.group(0))
    except ValueError as error:
        raise PlannerError(f"planner output is not valid JSON: {error}") from error

    raw_units = payload.get("units")
    if not isinstance(raw_units, list):
        raise PlannerError("planner output has no `units` list")

    units: list[Unit] = []
    excuses: dict[str, dict[str, str]] = {}
    seen: set[str] = set()

    # Whatever refuses the reply, the ids read so far are kept on the error as evidence.
    try:
        for index, raw in enumerate(raw_units):
            if not isinstance(raw, dict):
                raise PlannerError(f"unit {index} is not an object")

            missing = {"id", "change", "title", "repo", "tier"} - raw.keys()
            if missing:
                raise PlannerError(f"unit {index} is missing {', '.join(sorted(missing))}")

            repos = known_repos()
            if repos and raw["repo"] not in repos:
                raise PlannerError(
                    f"unit {raw['id']} has unknown repo {raw['repo']!r} "
                    f"(expected one of {', '.join(repos)})"
                )
            if new_spelling(Place.VALUE, str(raw["tier"])) not in TEST_KIND_TAGS:
                raise PlannerError(
                    f"unit {raw['id']} has unknown tier {raw['tier']!r} "
                    f"(expected one of {', '.join(TEST_KIND_TAGS)})"
                )
            if raw["id"] in seen:
                raise PlannerError(f"duplicate unit id {raw['id']!r}")
            seen.add(raw["id"])
            if "needs_less_urgent" in raw:
                excuses[raw["id"]] = _read_excuses(raw)

            units.append(
                Unit(
                    id=raw["id"],
                    change=raw["change"],
                    title=raw["title"],
                    repo=raw["repo"],
                    tier=raw["tier"],
                    project=_unit_project(raw, groups),
                    split=_unit_split(raw, groups),
                    depends_on=tuple(raw.get("depends_on") or ()),
                    estimated_lines=int(raw.get("estimated_lines") or 0),
                    groups=tuple(raw.get("groups") or ()),
                )
            )
        joins = _read_joins(payload.get("joins"))
        _check_dependencies(units, known or set())
        if groups is not None:
            _check_priority_edges(units, excuses, groups, context, change)
            carried = {number for join in joins if not join.unit for number in join.groups}
            _check_groups(units, groups, built or set(), carried)
            check_flagged_groups(units, groups)
        _check_ceiling(units, groups, calibrations)
        if joins:
            if context is None:
                raise PlannerError("the planner proposed a join, and none is expected here")
            try:
                check_joins(
                    joins,
                    context=context,
                    plan=units,
                    change=change,
                    groups=groups or [],
                    built=built or set(),
                    ceiling=active().global_limits.max_unit_lines,
                    calibrations=calibrations,
                )
            except JoinRefused as error:
                raise PlannerError(str(error)) from error
    except PlannerError as error:
        error.units = tuple(u.id for u in units)
        raise
    return Plan(units=tuple(units), joins=tuple(joins))


def _read_excuses(raw: dict) -> dict[str, str]:
    """The `needs_less_urgent` of a unit object: each dependency it lists, with a reason."""
    found = raw["needs_less_urgent"]
    if not isinstance(found, dict):
        raise PlannerError(
            f"unit {raw['id']} has a `needs_less_urgent` that is not an object of "
            "dependency ids to reasons"
        )
    for dependency, reason in found.items():
        if dependency not in (raw.get("depends_on") or ()):
            raise PlannerError(
                f"unit {raw['id']} excuses {dependency!r} in `needs_less_urgent` "
                "but does not list it in `depends_on`"
            )
        if not isinstance(reason, str) or not reason.strip():
            raise PlannerError(
                f"unit {raw['id']} gives no reason for {dependency!r} in `needs_less_urgent`"
            )
    return dict(found)


def _first_group(raw: dict, groups: list[TaskGroup] | None) -> TaskGroup | None:
    """The first group a planned unit lists that is in `groups`: where its shape is read from."""
    by_number = {group.number: group for group in groups or ()}
    return next((by_number[n] for n in raw.get("groups") or () if n in by_number), None)


def _unit_project(raw: dict, groups: list[TaskGroup] | None) -> str:
    """The project a planned unit is for: the one it names, else that of its first group."""
    if raw.get("project"):
        return str(raw["project"])
    first = _first_group(raw, groups)
    return first.project if first else "."


def _unit_split(raw: dict, groups: list[TaskGroup] | None) -> str:
    """The e2e-test split a planned unit is in: that of its first group, never the model's word."""
    first = _first_group(raw, groups)
    return first.split if first else REST_SPLIT


def unit_priority(unit: Unit, catalog: Mapping[str, Sequence[TaskGroup]]) -> int:
    """The most urgent priority among the groups `unit` builds, carried ones
    included; normal when none is in the catalog. Set in code, never asked of the model."""
    found = [
        group.priority
        for member in unit.members()
        for group in catalog.get(member.change, ())
        if group.number in member.groups
    ]
    return min(found, default=Priority.NORMAL)


def promote_ancestors(
    store: UnitStore, catalog: Mapping[str, Sequence[TaskGroup]]
) -> list[tuple[str, int, str]]:
    """Give each unit that has not started the most urgent priority among its groups and
    every unit that waits on it, and name the waiter that gives it (of equals, the id that
    sorts first). Recomputed at every pass, so a promotion lapses with its waiter; a unit
    that has started is never changed. A waiter counts at its stored priority once it has
    started and at its own before, which agree through chains. A unit none of whose groups
    is in the catalog has no groups to read, so it keeps the priority it was stored with,
    except that one carrying a promotion falls back to normal when the promotion lapses: its
    own priority is not recorded apart from the promoted one.
    Returns each unit now promoted by this pass as (id, priority, waiter)."""
    promoted: list[tuple[str, int, str]] = []
    units = [unit for unit in store.all() if unit.state != UnitState.UNPLANNED]

    def own_priority(unit: StoredUnit) -> int:
        known = any(
            group.number in member.groups
            for member in unit.members()
            for group in catalog.get(member.change, ())
        )
        if known or unit.promoted_from:
            return unit_priority(unit, catalog)
        return unit.priority

    own = {unit.id: own_priority(unit) for unit in units if unit.unstarted}
    view = [
        unit.model_copy(update={"priority": own[unit.id]}) if unit.id in own else unit
        for unit in units
    ]
    for unit in view:
        if unit.id not in own:
            continue
        waiters = waiting_on_me(unit, view)
        best = min(waiters, key=lambda waiter: (waiter.priority, waiter.id), default=None)
        if best is not None and best.priority < own[unit.id]:
            priority, source = best.priority, best.id
        else:
            priority, source = own[unit.id], ""
        stored = store.get(unit.id)
        if (stored.priority, stored.promoted_from) != (priority, source):
            store.set_promotion(unit.id, priority, source)
            if source:
                promoted.append((unit.id, priority, source))
    return promoted


def _read_joins(raw_joins: object) -> list[Join]:
    if raw_joins is None:
        return []
    if not isinstance(raw_joins, list):
        raise PlannerError("planner output has a `joins` that is not a list")
    joins: list[Join] = []
    for index, raw in enumerate(raw_joins):
        if not isinstance(raw, dict) or not isinstance(raw.get("onto"), str):
            raise PlannerError(f"join {index} is not an object naming the unit it goes `onto`")
        try:
            if "unit" in raw:
                joins.append(Join(onto=raw["onto"], unit=raw["unit"]))
            else:
                joins.append(
                    Join(
                        onto=raw["onto"],
                        change=raw["change"],
                        groups=tuple(int(n) for n in raw["groups"]),
                        estimated_lines=int(raw["estimated_lines"]),
                    )
                )
        except (KeyError, TypeError, ValueError) as error:
            raise PlannerError(
                f"join {index} onto {raw['onto']} is malformed: {error!r}"
            ) from error
    return joins


def plan_kind(unit: Unit, groups: Sequence[TaskGroup] | None) -> Kind:
    """The kind a planned unit is calibrated as: its flag is the first flagged group it carries."""
    by_number = {group.number: group for group in groups or ()}
    flag = next(
        (by_number[n].flag for n in unit.groups if n in by_number and by_number[n].flag), ""
    )
    return Kind(repo=unit.repo, tier=unit.tier, flag=flag)


def _check_ceiling(
    units: list[Unit],
    groups: Sequence[TaskGroup] | None = None,
    found: Mapping[Kind, Calibration] | None = None,
) -> None:
    """No unit is estimated over the ceiling, after its kind's calibration ratio.

    A single group over it is reported as `GroupTooLarge` before any combined
    unit is: that one is fixed in tasks.md, and re-asking would only spend
    attempts on it.
    """
    ceiling = active().global_limits.max_unit_lines
    applying = {unit.id: applied(found, plan_kind(unit, groups)) for unit in units}
    oversized = [
        unit
        for unit in units
        if calibrated(unit.estimated_lines, applying[unit.id].ratio) > ceiling
    ]

    for unit in oversized:
        if len(unit.groups) == 1:
            raise GroupTooLarge(
                f"group {unit.groups[0]} of {unit.change} is estimated at "
                f"{unit.estimated_lines} changed lines"
                f"{_calibration_note(unit, applying[unit.id])}, "
                f"over the ceiling of {ceiling} — "
                "no unit can hold it, so its tasks must be split in tasks.md"
            )
    if oversized:
        unit = oversized[0]
        raise PlannerError(
            f"unit {unit.id} is estimated at {unit.estimated_lines} changed lines"
            f"{_calibration_note(unit, applying[unit.id])}, over "
            f"the ceiling of {ceiling} — its groups must go in more than one unit"
            f"{_split_advice(unit, applying[unit.id], ceiling, groups)}"
        )


def _split_advice(
    unit: Unit, found: Calibration, ceiling: int, groups: Sequence[TaskGroup] | None
) -> str:
    """How to split a unit that is over the ceiling by its kind's ratio; nothing without one."""
    if found.ratio == 1.0:
        return ""
    return (
        f": split it by group, since a unit of {plan_kind(unit, groups).label} may carry at most "
        f"{largest_raw(ceiling, found.ratio)} raw estimated lines (the largest raw estimate "
        f"allowed) and this one carries {len(unit.groups)} groups"
    )


def _calibration_note(unit: Unit, found: Calibration) -> str:
    """What the estimate comes to once its kind's ratio is applied; nothing when there is none."""
    if found.ratio == 1.0:
        return ""
    return (
        f" (calibrated {calibrated(unit.estimated_lines, found.ratio)}: ratio "
        f"{found.ratio:.2f} from {found.samples} samples)"
    )


def _check_groups(
    units: list[Unit], groups: list[TaskGroup], built: set[int], carried: set[int]
) -> None:
    """Every task group is built exactly once, by a unit in its own repo.

    The planner is a model, and can hand a group tagged for one repo to a
    unit in the other — which would be built in the wrong checkout, against
    files that are not there. The tags are already
    validated on the change's own PR (`work_graph`), so they are the authority
    here and the plan is what gets checked against them.
    """
    by_number = {group.number: group for group in groups}
    claimed: dict[int, str] = {}

    for unit in units:
        in_splits = {n: by_number[n].split for n in unit.groups if n in by_number}
        if len(set(in_splits.values())) > 1:
            named = ", ".join(f"group {n} is in {split}" for n, split in in_splits.items())
            raise PlannerError(
                f"unit {unit.id} mixes e2e-test splits ({named}) — a unit is in one split, "
                "so each split's groups are a unit of their own"
            )
        for number in unit.groups:
            group = by_number.get(number)
            if group is None:
                raise PlannerError(
                    f"unit {unit.id} claims group {number}, which is not in tasks.md"
                )
            if group.repo != unit.repo:
                raise PlannerError(
                    f"unit {unit.id} is for {unit.repo} but claims group {number}, "
                    f"which is tagged [{group.repo}]"
                )
            if group.project != unit.project:
                raise PlannerError(
                    f"unit {unit.id} is for project {unit.project!r} of {unit.repo} but claims "
                    f"group {number}, which is tagged for project {group.project!r}"
                )
            if group.split != unit.split:
                raise PlannerError(
                    f"unit {unit.id} is in e2e-test split {unit.split!r} but claims group "
                    f"{number}, which is in split {group.split!r}"
                )
            if number in built:
                raise PlannerError(
                    f"unit {unit.id} claims group {number}, which a merged unit has "
                    "already built — it is in main, and rebuilding it on a branch cut "
                    "from main would redo work that is already there"
                )
            if number in claimed:
                raise PlannerError(
                    f"group {number} is claimed by both {claimed[number]} and {unit.id} — "
                    "it would be built twice, on two branches that then conflict"
                )
            if number in carried:
                raise PlannerError(
                    f"group {number} is claimed by unit {unit.id} and carried by a join — "
                    "it would be built twice"
                )
            claimed[number] = unit.id

    # `built` is what merged units already landed: after part of a change
    # merges, a re-plan legitimately covers only the rest.
    unbuilt = sorted(set(by_number) - set(claimed) - built - carried)
    if unbuilt:
        raise PlannerError(
            f"no unit builds group(s) {', '.join(str(n) for n in unbuilt)} — "
            "that work would be dropped from the change while its spec is archived as done"
        )


def check_flagged_groups(units: list[Unit], groups: list[TaskGroup]) -> None:
    """The acceptance and independence checks of a plan, for a caller that changed its edges."""
    _check_acceptance(units, groups)
    _check_independent(units, groups)


def _check_acceptance(units: list[Unit], groups: list[TaskGroup]) -> None:
    """The acceptance group is a unit of its own, built after every unit it
    exercises — it drives the finished surface, so it cannot share a branch
    with half of it or start before the rest is in. A group merged already
    needs no edge; a [narrow] group comes after it instead."""
    accepting = {g.number for g in groups if g.flag == "acceptance"}
    exercised = {g.number for g in groups if g.flag not in ("acceptance", "narrow")}
    index = {unit.id: unit for unit in units}

    for unit in units:
        if not accepting & set(unit.groups):
            continue
        if set(unit.groups) - accepting:
            raise PlannerError(
                f"unit {unit.id} combines the [acceptance] group with other work — it "
                "exercises what the rest of the change built, so it is a unit of its own"
            )
        waited_for = _upstream(index, unit.id, set())
        missing = [
            other.id
            for other in units
            if other.id != unit.id and exercised & set(other.groups) and other.id not in waited_for
        ]
        if missing:
            raise PlannerError(
                f"acceptance unit {unit.id} does not wait for {', '.join(missing)} — it would "
                "exercise the change before that work is in"
            )


def _upstream(index: dict[str, Unit], unit_id: str, seen: set[str]) -> set[str]:
    """Every unit of the plan `unit_id` waits for, directly or through others."""
    for dependency in index[unit_id].depends_on:
        if dependency in index and dependency not in seen:
            seen.add(dependency)
            _upstream(index, dependency, seen)
    return seen


def _check_independent(units: list[Unit], groups: list[TaskGroup]) -> None:
    """A group marked `Independent:` is a unit of its own that waits for no
    other unit of its change — it was written to stand alone, so chaining it
    behind its neighbours would only hold it up. What its `Needs:` lines name
    belongs to other changes, and stays."""
    independent = {g.number for g in groups if g.independent}
    narrowing = {g.number for g in groups if g.flag == "narrow"}
    index = {unit.id: unit for unit in units}
    standing = [unit for unit in units if independent & set(unit.groups)]
    for unit in units:
        if narrowing & set(unit.groups):
            waited_for = _upstream(index, unit.id, set())
            missing = [other.id for other in standing if other.id not in waited_for]
            if missing:
                raise PlannerError(
                    f"narrowing unit {unit.id} does not wait for {', '.join(missing)} — it "
                    "would remove the old half of the shape before that work is in"
                )
        if not independent & set(unit.groups):
            continue
        if set(unit.groups) - independent:
            raise PlannerError(
                f"unit {unit.id} combines an `Independent:` group with other work — it "
                "stands alone, so it is a unit of its own"
            )
        own = [d for d in unit.depends_on if d.startswith(f"{unit.change}/")]
        if own:
            raise PlannerError(
                f"unit {unit.id} holds an `Independent:` group but depends on "
                f"{', '.join(own)} of its own change — it waits for nothing there"
            )


def _check_dependencies(units: list[Unit], known: set[str]) -> None:
    """`known` is the units the store already has.

    A dependency naming one of those is legitimate: once a unit is in flight the
    planner stops proposing it, while the units behind it still depend on it.
    Requiring every dependency to appear in the returned graph made a change
    unplannable the moment its first unit opened.
    """
    known = known | {unit.id for unit in units}

    for unit in units:
        for dependency in unit.depends_on:
            if dependency not in known:
                raise PlannerError(
                    f"unit {unit.id} has unknown dependency {dependency!r} — "
                    "it would wait for work nobody is going to build"
                )

    # A cycle schedules nothing, and shows up as a pipeline that has quietly
    # stopped rather than as an error.
    index = {unit.id: unit for unit in units}
    visiting: set[str] = set()
    done: set[str] = set()

    def visit(unit_id: str, path: list[str]) -> None:
        if unit_id in done:
            return
        if unit_id in visiting:
            raise PlannerError(f"dependency cycle: {' -> '.join([*path, unit_id])}")
        visiting.add(unit_id)
        for dependency in index[unit_id].depends_on:
            # A dependency outside this plan is a unit already in flight or
            # merged. It cannot close a cycle here: whatever it waits on is
            # older still, so nothing routes back into the new graph.
            if dependency in index:
                visit(dependency, [*path, unit_id])
        visiting.discard(unit_id)
        done.add(unit_id)

    for unit in units:
        visit(unit.id, [])


def _check_priority_edges(
    units: Sequence[Unit],
    excuses: Mapping[str, Mapping[str, str]],
    groups: Sequence[TaskGroup],
    context: JoinContext | None,
    change: str | None,
) -> None:
    """Refuse a dependency on a less urgent unit that has not started, unless it is excused.

    A target is judged by the priority of its groups, never by its stored value, which a
    promotion may have raised. A target that has started or finished is left alone: the
    wait on it is already there.
    """
    catalog: dict[str, Sequence[TaskGroup]] = dict(context.catalog) if context else {}
    # The groups are those of the change being planned, whatever its units name.
    catalog |= {name: groups for name in ({change} if change else {u.change for u in units})}
    stored = {unit.id: unit for unit in context.stored} if context else {}
    planned = {unit.id: unit for unit in units}
    refused: list[str] = []
    for unit in units:
        own = unit_priority(unit, catalog)
        for dependency in unit.depends_on:
            target = planned.get(dependency)
            held = stored.get(dependency)
            if held is not None and not held.unstarted:
                continue
            target = target or held
            if target is None or dependency in excuses.get(unit.id, {}):
                continue
            theirs = unit_priority(target, catalog)
            if theirs > own:
                refused.append(
                    f"unit {unit.id} (priority {own}) depends on {dependency} "
                    f"(priority {theirs}), which is less urgent and has not started — drop "
                    f"the edge, or give the reason in `needs_less_urgent`"
                )
    if refused:
        # The first line is all a plan record keeps, so it says how many edges follow.
        if len(refused) > 1:
            refused[0] += f" (and {len(refused) - 1} more)"
        raise PlannerError("\n".join(refused))


PROMPT = """\
You are planning units of work for a spec-driven pipeline. Return JSON only.

A **unit** is one PR's worth of work in exactly ONE repo. Repos: {repos}.
Tiers: {tiers} (e2e-test needs the live local stack and is serialized). A group tagged
`[unit-test]` (or the old `[{old_unit_test}]`) is tier
`unit-test`; one tagged `[integration-test]` is tier `integration-test`; one tagged
`[e2e-test]` (or the old `[{old_e2e}]`) is tier `e2e-test`, and a
unit's tier is the widest tier of its groups.

Rules the graph must satisfy:
- A unit never spans repos. Every task group heading carries its own repo
  tag — `## 2. [{example_repo}] [unit-test] ...` — and that tag decides which unit
  the group can belong to. A unit's `groups` must ALL carry that unit's repo
  tag. Putting one repo's group in another repo's unit is the most common
  mistake here and is rejected outright.
- A unit is in one repo and one project. A group's project is shown on its
  heading below as `(project <path>)` when it is not the repo's root; a unit
  never takes groups tagged for different projects, and a join never crosses
  projects.
- A unit is in one e2e-test split: a group's `Split:` line, `rest` when it has none,
  shown on its heading below as `(split <name>)` when it is not `rest`. Groups of
  different splits are never in one unit, even when they are small and consecutive
  in the same repo: write each split's groups as a unit of its own. A join never
  crosses splits.
- Every group in the change must be claimed by exactly one unit: none left
  out, none in two units. The exception is a group whose heading is marked
  `(built by <unit id>)`: it is taken, so never claim it and return no unit
  for it. Dependencies on the unit that builds it stay valid.
- Group consecutive task groups **in the same repo** together until the
  estimate reaches about {min_lines} changed lines, so a chain of small groups
  doesn't become a stack of trivial PRs. Groups in different repos are never
  combined, however small, and consecutive numbering does not imply the same
  repo. Stop earlier when finishing a group unblocks other units.
- Never combine groups into a unit estimated over {max_lines} changed lines:
  a plan with such a unit is rejected. A single group estimated over it
  cannot be planned at all — give it its honest estimate in a unit of its own
  and it will be reported as needing its tasks split.
- `estimated_lines` is your estimate of additions plus deletions across
  every file the group touches: source, tests, docs, fixtures and the
  changelog included, and excluding generated files such as lockfiles. For a
  group that removes or rewrites code, count the removed lines too. When
  unsure, estimate high: the host counts what actually lands.
- Dependencies in the same repo may be in_review — the unit stacks on them.
  A cross-repo dependency means the dependent waits for a merge, so state it
  and keep the order right.
- Depend on a unit only for code it introduces that this one needs, for overlapping
  files or modules the two touch, or for an API shape the other establishes; those are
  the only reasons. Groups being next to each other is not one: do not make a more
  urgent unit depend on a less urgent one merely because the groups are adjacent, and
  do not chain independent groups. A unit takes the most urgent priority of its
  groups. A group's priority is shown on its heading, and a unit's below.
- A unit may list in `needs_less_urgent` a dependency it must keep on a less urgent unit
  that has not started, each with the reason; a plan with such a dependency and no
  reason is refused.
- Place new work against what is already in flight below, not against main:
  if an in-flight unit already adds what a new one needs, depend on it.
- A unit shown below as unstarted must not be made to depend, directly or
  through other units, on a unit of the change being planned: nothing earlier
  waits for a unit of this change, and a dependency like that closes a cycle.
- A group flagged `[contract]` widens a shape another repo consumes. The
  group flagged `[narrow]` removes the old half, so its unit depends on every
  unit that migrates a consumer, and nothing may depend on it. A consumer of
  the old shape exists until it is migrated and picks the change up — that is
  the window the narrowing unit waits out. This applies only across the repo
  boundary; a contract inside one repo needs no such ordering, because a
  change and its callers land in the same commit.
- The group flagged `[acceptance]` drives what the change built the way its
  consumer does. Give it a unit of its own, never combined with another group,
  and make that unit depend on every unit building the change's other groups
  (a `[narrow]` group aside, which comes after it).
- A group with an `Independent: <reason>` line stands alone. Give it a unit of
  its own, never combined with another group. That unit depends on no unit of
  its own change; it still depends on what its `Needs:` lines name. The next
  group's unit depends on the last unit before the independent one, as if the
  independent group were not there. An `[acceptance]` or `[narrow]` unit also
  depends on the independent unit.

How the repos relate:
{relationships}

{calibration}Changes ready to plan (their tasks.md):
{changes}

Units already in flight:
{in_flight}

Joining: a unit marked *unstarted* has no branch, commits or pull request yet,
so it can take in more work. Those units, and the change above, are all
candidates: any two unstarted units may be joined as well as a group of the
change above onto one. Join work that belongs together first: groups of one change,
or groups of different changes that touch the same or closely related files or
modules. Among candidates that fit equally well, the more urgent work is joined first,
so a less urgent item does not take a partner a more urgent one with similar files
could use. A priority never overrides a better fit and never joins unrelated work. The
unit takes the most urgent priority of its groups. Put a join in `joins` instead of a
unit of its own when you would otherwise have made the later work depend on the earlier *because
they overlap* — the same files or modules — and the pair is small. Do not join
two units merely because both are small. The unit that stays is the earlier.
Every join must satisfy all of these, and a plan with one that does not is
rejected:
- same repo and compatible kinds (`unit-test` and `integration-test` together, `e2e-test`
  only with `e2e-test`), and the same e2e-test split (a unit in flight shows its split
  when it is not `rest`);
- a straight line: the later depends on the earlier (or would, for a group of
  the change above), nothing else depends on the earlier, and the later waits
  on nothing else unfinished;
- neither has started — never name a unit not marked unstarted;
- no group involved is flagged `[acceptance]`, `[contract]` or `[narrow]`, or
  has a `Separate:` or `Independent:` line;
- the two estimates together stay at or under {max_lines} changed lines.{join_raw}
A unit joined to may be joined to again, in order along the line, while it
stays under that ceiling.

Respond with exactly this shape and nothing else (`joins` may be empty):
{{"units": [{{"id": "<change>/<n>", "change": "...", "title": "...",
  "repo": "...", "tier": "unit-test|integration-test|e2e-test", "depends_on": ["<unit id>"],
  "estimated_lines": 0, "groups": [1],
  "needs_less_urgent": {{"<unit id>": "<reason>"}}}}],
  "joins": [{{"onto": "<unit id>", "change": "<the change above>",
  "groups": [1], "estimated_lines": 0}}, {{"onto": "<unit id>", "unit": "<unit id>"}}]}}
"""


def in_flight_item(unit: StoredUnit) -> dict:
    """A unit as the planner is shown it, and whether it may be joined."""
    return {
        "id": unit.id,
        "repo": unit.repo,
        "project": unit.project,
        "split": unit.split,
        "branch": unit.branch,
        "state": unit.state,
        "unstarted": unit.unstarted,
        "tier": unit.tier,
        "priority": unit.priority,
        "estimated_lines": unit.estimated_lines,
        "depends_on": list(unit.depends_on),
        "taken": [[member.change, list(member.groups)] for member in unit.members()],
        "builds": "; ".join(
            f"{member.change} group(s) {', '.join(str(n) for n in member.groups)}"
            for member in unit.members()
        ),
    }


def split_note(item: dict) -> str:
    """`split <name>, ` for a unit outside `rest`, else nothing."""
    split = item.get("split", REST_SPLIT)
    return "" if split == REST_SPLIT else f"split {split}, "


def _in_flight_line(item: dict) -> str:
    line = f"- {item['id']} [{item['repo']}] {item.get('branch', '')} ({item.get('state', '?')})"
    if "priority" in item:
        line += f" priority {item['priority']}"
    if item.get("unstarted"):
        line += (
            f" unstarted, {item.get('tier', '?')}, "
            f"{split_note(item)}est {item.get('estimated_lines', 0)} lines, "
            f"builds {item.get('builds', '?')}, depends on "
            f"{', '.join(item.get('depends_on') or []) or 'nothing'}"
        )
    elif item.get("builds"):
        # Started units too: the groups one carries are taken, and the planner
        # has to see that to leave them out.
        line += f" builds {item['builds']}"
    return line


# What the calibration section may add to the prompt, in characters; examples are dropped
# first, and kinds are capped by `global_limits.calibration_kinds_listed`.
SECTION_MAXIMUM = 2000
TITLE_MAXIMUM = 80


def _listed(found: Mapping[Kind, Calibration] | None) -> list[Kind]:
    """The kinds the planner is told about: above 1, the most samples first, ties by name."""
    if not active().global_limits.calibrate_estimates or not found:
        return []
    above = sorted(
        (kind for kind in found if found[kind].ratio > 1.0),
        key=lambda kind: (-found[kind].samples, kind.label),
    )
    return above[: active().global_limits.calibration_kinds_listed]


def _kind_lines(kind: Kind, found: Calibration, shown: Sequence[StoredUnit]) -> list[str]:
    limits = active().global_limits
    lines = [
        f"- {kind.label}: {found.ratio:.2f} from {found.samples} samples; largest raw estimate "
        f"{largest_raw(limits.max_unit_lines, found.ratio)}, group up to about "
        f"{largest_raw(limits.min_unit_lines, found.ratio)} raw"
    ]
    lines += [
        f'    "{unit.title[:TITLE_MAXIMUM]}": estimated {unit.estimated_lines}, '
        f"landed {unit.actual_lines}"
        for unit in shown
    ]
    return lines


def _fitted(
    found: Mapping[Kind, Calibration] | None,
    examples: Mapping[Kind, Sequence[StoredUnit]] | None = None,
) -> tuple[str, list[Kind]]:
    """The calibration section and the kinds it lists. Over `SECTION_MAXIMUM` the examples go
    first, the same number from every kind, then the kinds with the fewest samples."""
    listed = _listed(found)
    if not found or not listed:
        return "", []
    ratios = dict(found)
    above = len([kind for kind in ratios if ratios[kind].ratio > 1.0])
    head = (
        "Estimates are your raw figures. Units of these kinds have landed above their\n"
        "estimates, and the check multiplies a unit's estimate by its kind's ratio before\n"
        "comparing it with the ceiling, so estimate and group with that in mind:\n"
    )
    shown = {kind: list((examples or {}).get(kind, ())) for kind in listed}
    most = max(len(units) for units in shown.values())

    def render(kinds: list[Kind], count: int) -> str:
        body = [
            line for kind in kinds for line in _kind_lines(kind, ratios[kind], shown[kind][:count])
        ]
        if above > len(kinds):
            body.append(f"({above - len(kinds)} more kinds left out)")
        return head + "\n".join(body) + "\n\n"

    attempts = [(listed, count) for count in range(most, -1, -1)]
    attempts += [(listed[:keep], 0) for keep in range(len(listed) - 1, 0, -1)]
    for kinds, count in attempts:
        text = render(kinds, count)
        if len(text) <= SECTION_MAXIMUM:
            return text, kinds
    return "", []


def _calibration_section(
    found: Mapping[Kind, Calibration] | None,
    examples: Mapping[Kind, Sequence[StoredUnit]] | None = None,
) -> str:
    """The ratios the plan check multiplies estimates by, for the kinds above 1, each with
    the largest raw estimate and the newest units behind it; empty when calibration is off
    or there are none."""
    return _fitted(found, examples)[0]


def _join_raw(
    found: Mapping[Kind, Calibration] | None,
    examples: Mapping[Kind, Sequence[StoredUnit]] | None = None,
) -> str:
    """The largest raw estimate of each kind the section lists, beside the ceiling the join
    text states."""
    kinds = _fitted(found, examples)[1]
    if not found or not kinds:
        return ""
    ceiling = active().global_limits.max_unit_lines
    figures = ", ".join(
        f"{kind.label}: {largest_raw(ceiling, found[kind].ratio)}" for kind in kinds
    )
    return f" For a calibrated kind that is the largest raw estimate it may carry ({figures})."


def _mark_built(
    change: str, tasks: str, in_flight: list[dict], groups: Sequence[TaskGroup] | None = None
) -> str:
    """`tasks` with `(priority N)` (and `(split <name>)` outside `rest`) on the heading of each
    of `groups` and `(built by <unit id>)` on that of each group a started unit builds."""
    priorities = {group.number: group.priority for group in groups or ()}
    splits = {group.number: group.split for group in groups or ()}
    built = {
        number: item["id"]
        for item in in_flight
        if not item.get("unstarted")
        for name, numbers in item.get("taken", ())
        if name == change
        for number in numbers
    }

    def mark(line: str) -> str:
        found = GROUP_NUMBER.match(line)
        unit_id = built.get(int(found["number"])) if found else None
        if found and int(found["number"]) in priorities:
            line += f" (priority {priorities[int(found['number'])]})"
        if found and splits.get(int(found["number"]), REST_SPLIT) != REST_SPLIT:
            line += f" (split {splits[int(found['number'])]})"
        if heading := GROUP_HEADING.match(line):
            _, project = split_repo_tag(heading["repo"], known_repos())
            if project:
                line += f" (project {project})"
        return f"{line} (built by {unit_id})" if unit_id else line

    return "\n".join(mark(line) for line in tasks.split("\n"))


def build_prompt(
    changes: dict[str, str],
    in_flight: list[dict],
    calibrations: Mapping[Kind, Calibration] | None = None,
    examples: Mapping[Kind, Sequence[StoredUnit]] | None = None,
    omitted: int = 0,
    groups: Sequence[TaskGroup] | None = None,
) -> str:
    return _prompt_and_parts(changes, in_flight, calibrations, examples, omitted, groups)[0]


def omitted_line(count: int) -> str:
    """The one line that stands for the landed units of other changes left out of the list."""
    return f"{count} merged or satisfied units of other changes are in the trunk and omitted"


def _prompt_and_parts(
    changes: dict[str, str],
    in_flight: list[dict],
    calibrations: Mapping[Kind, Calibration] | None,
    examples: Mapping[Kind, Sequence[StoredUnit]] | None,
    omitted: int,
    groups: Sequence[TaskGroup] | None = None,
    previous_refusal: str = "",
) -> tuple[str, dict[str, int]]:
    """The prompt, and the size in bytes of the parts a person can cut."""
    first = next(iter(changes), "")
    changes_text = (
        "\n\n".join(
            f"### {name}\n{_mark_built(name, tasks, in_flight, groups if name == first else None)}"
            for name, tasks in changes.items()
        )
        or "(none)"
    )
    lines = [_in_flight_line(item) for item in in_flight]
    if omitted:
        lines.append(omitted_line(omitted))
    in_flight_text = "\n".join(lines) or "(none)"

    workspace = active()
    repos = list(workspace.repos)
    relationships = "\n\n".join(
        f"{name}: {repo.relationships.strip()}"
        for name, repo in workspace.repos.items()
        if repo.relationships.strip()
    )
    for name, repo in workspace.repos.items():
        if repo.consumes:
            relationships += f"\n\n{name} consumes {', '.join(repo.consumes)}."
    relationships = relationships.strip() or "(independent)"
    calibration = _calibration_section(calibrations, examples)
    prompt = PROMPT.format(
        repos=", ".join(repos) or "(none configured)",
        example_repo=repos[0] if repos else "repo",
        tiers=", ".join(TEST_KIND_TAGS),
        old_unit_test=OLD_UNIT_TEST,
        old_e2e=OLD_E2E,
        min_lines=workspace.global_limits.min_unit_lines,
        max_lines=workspace.global_limits.max_unit_lines,
        relationships=relationships,
        calibration=calibration,
        join_raw=_join_raw(calibrations, examples),
        changes=changes_text,
        in_flight=in_flight_text,
    )
    if previous_refusal:
        prompt += (
            "\n\nYour previous plan was refused. Plan again so that it does not recur:\n"
            f"{previous_refusal}"
        )
    parts = {
        "tasks.md": len(changes_text.encode()),
        "relationships": len(relationships.encode()),
        "calibration": len(calibration.encode()),
        "in-flight list": len(in_flight_text.encode()),
    }
    return prompt, {"template": len(prompt.encode()) - sum(parts.values()), **parts}


def _ask(
    prompt: str,
    runtime: AgentRuntime | None,
    change: str = "",
    parts: Mapping[str, int] | None = None,
) -> str:
    """The graph call: no worktree and no tools, answered from the prompt
    alone. A refusal raises as it does for any run; any other failed run
    fails the attempt on what the runtime said, never read as a plan. A prompt over the
    runtime's safe size fails before the request is made, naming the size of each part."""
    agent = runtime or runtimes.active()
    request = recorded(
        AgentRequest(prompt=prompt, permission_mode="allowed_tools_only", change=change),
        agent,
        node=OverheadNode.PLAN,
        change=change,
        say=print,
    )
    try:
        check_prompt_size(request, agent.prompt_transport)
    except PromptTooLarge as error:
        sizes = "".join(f"\n  {name}: {size} bytes" for name, size in (parts or {}).items())
        raise PlannerError(f"{error}{sizes}") from error
    result = agent.run(request)
    if not result.ok:
        raise PlannerError(f"the graph call failed: {result.error}")
    return result.text


def plan_round(
    *,
    changes: dict[str, str],
    in_flight: list[dict],
    groups: list[TaskGroup] | None = None,
    built: set[int] | None = None,
    known: set[str] | None = None,
    context: JoinContext | None = None,
    calibrations: Mapping[Kind, Calibration] | None = None,
    examples: Mapping[Kind, Sequence[StoredUnit]] | None = None,
    run_claude: RunClaude | None = None,
    runtime: AgentRuntime | None = None,
    omitted: int = 0,
    previous_refusal: str = "",
) -> Plan:
    """Ask for a graph and return it, or raise `PlannerError`.

    An empty plan is a normal answer: every change may be waiting on review.
    Joins the planner proposes are checked against `context` and returned with
    the units; a caller that passes no `context` accepts none.
    """
    prompt, parts = _prompt_and_parts(
        changes, in_flight, calibrations, examples, omitted, groups, previous_refusal
    )
    answer = (
        run_claude(prompt)
        if run_claude
        else _ask(prompt, runtime, change=next(iter(changes), ""), parts=parts)
    )
    return parse_plan(
        answer,
        groups=groups,
        built=built,
        known=known,
        change=next(iter(changes), None),
        context=context,
        calibrations=calibrations,
    )
