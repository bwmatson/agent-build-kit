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
from agent_build_kit.config import active
from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.joins import JoinContext, JoinRefused, check_joins
from agent_build_kit.pipeline.unit_store import StoredUnit
from agent_build_kit.pipeline.units import Join, Priority, Unit
from agent_build_kit.pipeline.work_graph import TIERS, TaskGroup, known_repos
from agent_build_kit.runtimes import AgentRequest
from agent_build_kit.runtimes.base import AgentRuntime

RunClaude = Callable[[str], str]

JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)


class PlannerError(Exception):
    """The proposed graph can't be trusted, so the round stops here."""


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
    seen: set[str] = set()

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
        if raw["tier"] not in TIERS:
            raise PlannerError(
                f"unit {raw['id']} has unknown tier {raw['tier']!r} "
                f"(expected one of {', '.join(TIERS)})"
            )
        if raw["id"] in seen:
            raise PlannerError(f"duplicate unit id {raw['id']!r}")
        seen.add(raw["id"])

        units.append(
            Unit(
                id=raw["id"],
                change=raw["change"],
                title=raw["title"],
                repo=raw["repo"],
                tier=raw["tier"],
                depends_on=tuple(raw.get("depends_on") or ()),
                estimated_lines=int(raw.get("estimated_lines") or 0),
                groups=tuple(raw.get("groups") or ()),
            )
        )

    joins = _read_joins(payload.get("joins"))
    _check_dependencies(units, known or set())
    if groups is not None:
        carried = {number for join in joins if not join.unit for number in join.groups}
        _check_groups(units, groups, built or set(), carried)
        _check_acceptance(units, groups)
        _check_independent(units, groups)
    _check_ceiling(units)
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
                ceiling=active().limits.max_unit_lines,
            )
        except JoinRefused as error:
            raise PlannerError(str(error)) from error
    return Plan(units=tuple(units), joins=tuple(joins))


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


def _check_ceiling(units: list[Unit]) -> None:
    """No unit is estimated over the ceiling.

    A single group over it is reported as `GroupTooLarge` before any combined
    unit is: that one is fixed in tasks.md, and re-asking would only spend
    attempts on it.
    """
    ceiling = active().limits.max_unit_lines
    oversized = [unit for unit in units if unit.estimated_lines > ceiling]

    for unit in oversized:
        if len(unit.groups) == 1:
            raise GroupTooLarge(
                f"group {unit.groups[0]} of {unit.change} is estimated at "
                f"{unit.estimated_lines} changed lines, over the ceiling of {ceiling} — "
                "no unit can hold it, so its tasks must be split in tasks.md"
            )
    if oversized:
        unit = oversized[0]
        raise PlannerError(
            f"unit {unit.id} is estimated at {unit.estimated_lines} changed lines, over "
            f"the ceiling of {ceiling} — its groups must go in more than one unit"
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


PROMPT = """\
You are planning units of work for a spec-driven pipeline. Return JSON only.

A **unit** is one PR's worth of work in exactly ONE repo. Repos: {repos}.
Tiers: {tiers} (tier2 needs the live local stack and is serialized).

Rules the graph must satisfy:
- A unit never spans repos. Every task group heading carries its own repo
  tag — `## 2. [{example_repo}] [tier1] ...` — and that tag decides which unit
  the group can belong to. A unit's `groups` must ALL carry that unit's repo
  tag. Putting one repo's group in another repo's unit is the most common
  mistake here and is rejected outright.
- Every group in the change must be claimed by exactly one unit: none left
  out, none in two units.
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
- Depend on a unit if it introduces code this one needs, if the two touch
  overlapping files or modules, or if this one relies on an API shape the
  other establishes.
- Place new work against what is already in flight below, not against main:
  if an in-flight unit already adds what a new one needs, depend on it.
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

Changes ready to plan (their tasks.md):
{changes}

Units already in flight:
{in_flight}

Joining: a unit marked *unstarted* has no branch, commits or pull request yet,
so it can take in more work. Those units, and the change above, are all
candidates: any two unstarted units may be joined as well as a group of the
change above onto one. Put a join in `joins` instead of a unit of its own when
you would otherwise have made the later work depend on the earlier *because
they overlap* — the same files or modules — and the pair is small. Do not join
two units merely because both are small. The unit that stays is the earlier.
Every join must satisfy all of these, and a plan with one that does not is
rejected:
- same repo and same tier;
- a straight line: the later depends on the earlier (or would, for a group of
  the change above), nothing else depends on the earlier, and the later waits
  on nothing else unfinished;
- neither has started — never name a unit not marked unstarted;
- no group involved is flagged `[acceptance]`, `[contract]` or `[narrow]`, or
  has a `Separate:` or `Independent:` line;
- the two estimates together stay at or under {max_lines} changed lines.
A unit joined to may be joined to again, in order along the line, while it
stays under that ceiling.

Respond with exactly this shape and nothing else (`joins` may be empty):
{{"units": [{{"id": "<change>/<n>", "change": "...", "title": "...",
  "repo": "...", "tier": "tier1|tier2", "depends_on": ["<unit id>"],
  "estimated_lines": 0, "groups": [1]}}],
  "joins": [{{"onto": "<unit id>", "change": "<the change above>",
  "groups": [1], "estimated_lines": 0}}, {{"onto": "<unit id>", "unit": "<unit id>"}}]}}
"""


def in_flight_item(unit: StoredUnit) -> dict:
    """A unit as the planner is shown it, and whether it may be joined."""
    return {
        "id": unit.id,
        "repo": unit.repo,
        "branch": unit.branch,
        "state": unit.state,
        "unstarted": unit.unstarted,
        "tier": unit.tier,
        "estimated_lines": unit.estimated_lines,
        "depends_on": list(unit.depends_on),
        "builds": "; ".join(
            f"{member.change} group(s) {', '.join(str(n) for n in member.groups)}"
            for member in unit.members()
        ),
    }


def _in_flight_line(item: dict) -> str:
    line = f"- {item['id']} [{item['repo']}] {item.get('branch', '')} ({item.get('state', '?')})"
    if item.get("unstarted"):
        line += (
            f" unstarted, {item.get('tier', '?')}, est {item.get('estimated_lines', 0)} lines, "
            f"builds {item.get('builds', '?')}, depends on "
            f"{', '.join(item.get('depends_on') or []) or 'nothing'}"
        )
    elif item.get("builds"):
        # Started units too: the groups one carries are taken, and the planner
        # has to see that to leave them out.
        line += f" builds {item['builds']}"
    return line


def build_prompt(changes: dict[str, str], in_flight: list[dict]) -> str:
    changes_text = (
        "\n\n".join(f"### {name}\n{tasks}" for name, tasks in changes.items()) or "(none)"
    )
    in_flight_text = "\n".join(_in_flight_line(item) for item in in_flight) or "(none)"

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
    return PROMPT.format(
        repos=", ".join(repos) or "(none configured)",
        example_repo=repos[0] if repos else "repo",
        tiers=", ".join(TIERS),
        min_lines=workspace.limits.min_unit_lines,
        max_lines=workspace.limits.max_unit_lines,
        relationships=relationships.strip() or "(independent)",
        changes=changes_text,
        in_flight=in_flight_text,
    )


def _ask(prompt: str, runtime: AgentRuntime | None) -> str:
    """The graph call: no worktree and no tools, answered from the prompt
    alone. A refusal raises as it does for any run; any other failed run
    fails the attempt on what the runtime said, never read as a plan."""
    result = (runtime or runtimes.active()).run(
        AgentRequest(prompt=prompt, permission_mode="allowed_tools_only")
    )
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
    run_claude: RunClaude | None = None,
    runtime: AgentRuntime | None = None,
) -> Plan:
    """Ask for a graph and return it, or raise `PlannerError`.

    An empty plan is a normal answer: every change may be waiting on review.
    Joins the planner proposes are checked against `context` and returned with
    the units; a caller that passes no `context` accepts none.
    """
    prompt = build_prompt(changes, in_flight)
    answer = run_claude(prompt) if run_claude else _ask(prompt, runtime)
    return parse_plan(
        answer,
        groups=groups,
        built=built,
        known=known,
        change=next(iter(changes), None),
        context=context,
    )
