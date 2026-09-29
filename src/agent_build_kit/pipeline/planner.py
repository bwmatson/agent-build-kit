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
import subprocess
from collections.abc import Callable

from agent_build_kit.config import active
from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.units import Unit
from agent_build_kit.pipeline.usage_guard import check_refusal
from agent_build_kit.pipeline.work_graph import TIERS, TaskGroup, known_repos
from agent_build_kit.runtimes.base import AgentRuntime

RunClaude = Callable[[str], str]

JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)


class PlannerError(Exception):
    """The proposed graph can't be trusted, so the round stops here."""


class InFlight(Frozen):
    """A unit that already exists, as context for placing new work."""

    id: str
    repo: str
    branch: str
    state: str


def parse_graph(
    output: str,
    *,
    groups: list[TaskGroup] | None = None,
    built: set[int] | None = None,
    known: set[str] | None = None,
) -> list[Unit]:
    """Read and verify a proposed graph, or raise `PlannerError`."""
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

    _check_dependencies(units, known or set())
    if groups is not None:
        _check_groups(units, groups, built or set())
        _check_acceptance(units, groups)
    return units


def _check_groups(units: list[Unit], groups: list[TaskGroup], built: set[int]) -> None:
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
            claimed[number] = unit.id

    # `built` is what merged units already landed: after part of a change
    # merges, a re-plan legitimately covers only the rest.
    unbuilt = sorted(set(by_number) - set(claimed) - built)
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

    def upstream(unit_id: str, seen: set[str]) -> set[str]:
        for dependency in index[unit_id].depends_on:
            if dependency in index and dependency not in seen:
                seen.add(dependency)
                upstream(dependency, seen)
        return seen

    for unit in units:
        if not accepting & set(unit.groups):
            continue
        if set(unit.groups) - accepting:
            raise PlannerError(
                f"unit {unit.id} combines the [acceptance] group with other work — it "
                "exercises what the rest of the change built, so it is a unit of its own"
            )
        waited_for = upstream(unit.id, set())
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
- `estimated_lines` is your estimate of additions plus deletions, excluding
  generated files such as lockfiles.
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

How the repos relate:
{relationships}

Changes ready to plan (their tasks.md):
{changes}

Units already in flight:
{in_flight}

Respond with exactly this shape and nothing else:
{{"units": [{{"id": "<change>/<n>", "change": "...", "title": "...",
  "repo": "...", "tier": "tier1|tier2", "depends_on": ["<unit id>"],
  "estimated_lines": 0, "groups": [1]}}]}}
"""


def build_prompt(changes: dict[str, str], in_flight: list[dict]) -> str:
    changes_text = (
        "\n\n".join(f"### {name}\n{tasks}" for name, tasks in changes.items()) or "(none)"
    )
    in_flight_text = (
        "\n".join(
            f"- {item['id']} [{item['repo']}] {item.get('branch', '')} ({item.get('state', '?')})"
            for item in in_flight
        )
        or "(none)"
    )

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
        relationships=relationships.strip() or "(independent)",
        changes=changes_text,
        in_flight=in_flight_text,
    )


def _claude(prompt: str) -> str:
    result = subprocess.run(
        ["claude", "-p", prompt, "--output-format", "text"],
        capture_output=True,
        text=True,
        check=False,
    )
    check_refusal(result)
    return result.stdout


def plan_round(
    *,
    changes: dict[str, str],
    in_flight: list[dict],
    groups: list[TaskGroup] | None = None,
    built: set[int] | None = None,
    known: set[str] | None = None,
    run_claude: RunClaude | None = None,
    runtime: AgentRuntime | None = None,
) -> list[Unit]:
    """Ask for a graph and return it, or raise `PlannerError`.

    An empty plan is a normal answer: every change may be waiting on review.
    """
    run_claude = run_claude or _claude
    return parse_graph(
        run_claude(build_prompt(changes, in_flight)), groups=groups, built=built, known=known
    )
