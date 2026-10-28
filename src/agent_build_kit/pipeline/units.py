"""Units of work: where the boundaries fall, and which may run now.

A change's `tasks.md` is a list of task groups. A unit is one PR's worth of
them, in one repo (docs/architecture.md). This module holds the
rules that turn one into the other, and the scheduling questions that follow:
what a unit stacks on, how deep its chain is, and which units are ready.

Everything here is pure. The planner that produces the estimates, and the
parts that talk to git and GitHub, live elsewhere — so these rules can be
argued with directly, in tests, rather than through a subprocess.

`ready_units`, `in_progress`, `in_progress_label` and `start_room` expect stored units: `pr` and
`branch`, `pushed` and `approved` exist only on those, and `unit_store` imports this module, so it
cannot be named here. Given plain `Unit`s they would see no pull request and no sign of a run.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Collection, Hashable, Iterable, Mapping, Sequence
from datetime import datetime
from enum import IntEnum, StrEnum
from pathlib import Path
from typing import Protocol, Self, runtime_checkable

from pydantic import Field

from agent_build_kit.compat_names import Place, TestKind, new_spelling
from agent_build_kit.config import REST_SPLIT, RepoConfig, active, active_checkout
from agent_build_kit.model import Frozen, TestTier, widest_kind
from agent_build_kit.pipeline import loaded_code
from agent_build_kit.pipeline.loaded_code import LoadedCode
from agent_build_kit.pipeline.shell import has_origin


class UnitState(StrEnum):
    PLANNED = "planned"
    RUNNING = "running"
    IN_REVIEW = "in_review"
    MERGED = "merged"
    # The pull request is merged and the unit waits for its checks to complete.
    SETTLING = "settling"
    CLOSED = "closed"
    FAILED = "failed"
    HELD = "held"
    SATISFIED = "satisfied"
    # Work the plan dropped; it may already have an open PR, so it is kept.
    UNPLANNED = "unplanned"
    # Ended by `abk retire`: finished, builds nothing, and no plan revives it.
    RETIRED = "retired"


# States a unit moves through. "running" means it is in the build/review loop:
# a worktree is open and an agent is working. "in_review" means the loop has
# passed and its PR is waiting for a human. It was called "open", after the
# PR's GitHub state, which read as unfinished for a unit that was done with
# everything the pipeline does to it (see unit_store).
PLANNED = UnitState.PLANNED
RUNNING = UnitState.RUNNING
IN_REVIEW = UnitState.IN_REVIEW
MERGED = UnitState.MERGED
SETTLING = UnitState.SETTLING
CLOSED = UnitState.CLOSED

# Stopped on something it could not get past; its feedback says what. Nothing
# retries it until someone requeues it (`abk requeue`), or, once, the pipeline does when a
# wait on another unit it was recorded in ends.
FAILED = UnitState.FAILED

# The pipeline is keeping its hands off this unit: a reviewer asked it to, the
# toolchain cannot build it, or a merge left it beyond the rebase cap (which a
# later merge releases). Not a lifecycle state like the ones above: those
# describe how far a unit has got, and this describes who is driving it.
HELD = UnitState.HELD

# A unit whose groups needed nothing: it added no commits of its own, and what
# was already at the tip passed unit-test. There is no diff, so no PR and nothing
# to review — the work arrived by another unit building ahead of its plan.
SATISFIED = UnitState.SATISFIED

IN_FLIGHT = (RUNNING, IN_REVIEW)

# States of a unit that builds nothing: nothing waits on it, follows it or counts its groups.
BUILDS_NOTHING = (UnitState.UNPLANNED, UnitState.RETIRED)

# A dependency in one of these waits on nothing any more: it has finished or was ended.
FINISHED_STATES = (MERGED, SATISFIED, CLOSED, UnitState.RETIRED)

# What a dependent may build on. A unit is not finished when it starts — it is
# finished when it has passed the build/review loop and unit-test and been pushed,
# which is what `in_review` means. `IN_FLIGHT` includes `running`, so using it here
# unblocked a dependent the moment its parent *began*, against a branch nothing
# had reviewed and which might not exist yet. The review loop, which can send a
# unit back three times, makes that window much wider. A satisfied unit belongs
# here too: it has nothing left to do and nothing that will change under it.
REVIEWED = (IN_REVIEW, SETTLING, MERGED, SATISFIED)


class Priority(IntEnum):
    """How urgent a unit is: 0 the most (the emergency lane), 5 the least. A value
    between the named ones is still valid and sorts as its integer."""

    EMERGENCY = 0
    FIX = 1
    HIGH = 2
    NORMAL = 3
    LOW = 4
    NICE_TO_HAVE = 5


class Member(Frozen):
    """Task groups of one change that a unit builds."""

    change: str
    groups: tuple[int, ...]


class Join(Frozen):
    """The planner's proposal that `onto` take in more work: an existing unit
    (`unit`), or a new change's groups (`change`, `groups`, and their
    estimate)."""

    onto: str
    unit: str = ""
    change: str = ""
    groups: tuple[int, ...] = ()
    estimated_lines: int = 0


class ManualStep(Frozen):
    """A step only a person can do, with the check the tick runs to see it is done."""

    slug: str
    text: str
    runbook: str = ""
    check: str = ""
    # The `Manual:` line it was declared on, 0 for a raised step.
    line: int = 0
    # Set once by the tick when the check passes; a step done stays done.
    done: bool = False
    # What the last check came to: `met`, `unmet`, `failed` or `timeout`; empty before the first.
    outcome: str = ""
    # The last line the last check printed, bounded and redacted.
    last_line: str = ""
    checked_at: datetime | None = None


class Unit(Frozen):
    id: str
    change: str
    title: str
    repo: str
    # Stored under the key `tier` until the readers are renamed; a value from before the rename
    # (the kind's old spelling) is read as the kind it meant.
    tier: TestKind
    project: str = "."
    # The e2e-test split all the unit's groups share; `rest` when they declare none.
    split: str = REST_SPLIT
    depends_on: tuple[str, ...] = ()
    # Every target a `Needs:` line names, whether linked as a dependency or already reached
    # through one; only the graph reads it, and draws an edge only for those also in `depends_on`.
    needs: tuple[str, ...] = ()
    # The targets of `needs` whose line waits for the merge (the word `merged`, or a group of
    # another repository), recomputed from `tasks.md` each tick; a subset of `needs`.
    merge_needs: tuple[str, ...] = ()
    estimated_lines: int = 0
    # The planner's review tier (`auto`, `light` or `full`); None for a unit planned without one.
    review_tier: str | None = None
    state: UnitState = PLANNED
    issue: int | None = None
    groups: tuple[int, ...] = ()
    joined: tuple[Member, ...] = ()
    priority: int = Field(default=Priority.NORMAL, ge=Priority.EMERGENCY, le=Priority.NICE_TO_HAVE)
    # The unit that waits on this one and gives it the priority it has; empty when the
    # priority is the unit's own.
    promoted_from: str = ""
    # The units that carry this one's groups after a replan replaced it; empty for a unit the
    # plan holds.
    superseded_by: tuple[str, ...] = ()
    # The steps only a person can do that this unit waits on, declared by its groups or raised.
    manual_steps: tuple[ManualStep, ...] = ()

    def members(self) -> tuple[Member, ...]:
        """Every change's groups this unit builds: its own first, then carried ones."""
        return (Member(change=self.change, groups=self.groups), *self.joined)

    def taking(
        self, taken: Sequence[Member], *, estimated_lines: int, kinds: Iterable[TestTier] = ()
    ) -> Self:
        """This unit with `taken` built after its own members, its estimate grown by
        `estimated_lines` and its kind the widest of its own and `kinds`, those of the work
        taken. Work of the change the unit already ends on extends that member rather than
        starting another."""
        members = list(self.members())
        for member in taken:
            if members[-1].change == member.change:
                groups = (*members[-1].groups, *member.groups)
                members[-1] = Member(change=member.change, groups=groups)
            else:
                members.append(member)
        return self.model_copy(
            update={
                "groups": members[0].groups,
                "joined": tuple(members[1:]),
                "estimated_lines": self.estimated_lines + estimated_lines,
                "tier": widest_kind([self.tier, *kinds]),
            }
        )

    def carries(self, change: str) -> bool:
        """Does this unit build any of `change`'s groups, its own or carried?"""
        return any(member.change == change for member in self.members())


class ProjectKey(Frozen):
    """A repo's project: what the limits on units in progress and build workers count."""

    repo: str
    project: str = "."


def project_tag(repo: str, project: str) -> str:
    """How a person spells a project: the repo, and `repo/project` unless it is the root."""
    return repo if project == "." else f"{repo}/{project}"


def project_key(unit: Unit) -> ProjectKey:
    """The project a unit is counted in: its repo and its project."""
    return ProjectKey(repo=unit.repo, project=unit.project)


def project_counts(
    graph: Sequence[Unit], slot_of: Callable[[Unit], Hashable] = project_key
) -> dict[Hashable, int]:
    """The units in progress (`in_progress`) in each slot (a project, unless `slot_of` names the
    account) that has any; no total is kept."""
    return count_by(graph, slot_of, lambda unit: in_progress(unit, graph))


def count_by_project(
    graph: Sequence[Unit], counts: Callable[[Unit], bool]
) -> dict[ProjectKey, int]:
    """How many units `counts` accepts in each project that has any."""
    return count_by(graph, project_key, counts)


def count_by[K: Hashable](
    graph: Sequence[Unit], key_of: Callable[[Unit], K], counts: Callable[[Unit], bool]
) -> dict[K, int]:
    """How many units `counts` accepts under each key of `key_of` that has any."""
    totals: dict[K, int] = {}
    for unit in graph:
        if counts(unit):
            key = key_of(unit)
            totals[key] = totals.get(key, 0) + 1
    return totals


@runtime_checkable
class Recorded(Protocol):
    """A unit as the store records it: the branch it is on and the pull requests it has had
    (`StoredUnit`, which this module cannot import)."""

    branch: str
    pulls: tuple[object, ...]


def branch_name(unit: Unit) -> str:
    """`spec/<change>/<n>` — deterministic, so a re-run reuses the branch.

    Nothing derived from the title or a timestamp: a renamed unit must land on
    the same branch, or the work already committed there is orphaned. The one
    place a unit's branch is spelled; the prefix is the setting the command
    policy and the poller use to recognise these branches.

    A unit with a merged pull request builds its late fix on the branch recorded for it
    (`<name>-fix<k>`), so the one name every builder reads follows the unit to its second pull
    request.
    """
    if isinstance(unit, Recorded) and unit.branch and unit.pulls:
        return unit.branch
    return f"{active().git.branch_prefix}{unit.id}"


def local_ref(base: str, repo: str | None = None) -> str:
    """The ref to build on locally for a PR base named `base`.

    A unit's own branch is local — its parent's worktree commits to it. The
    trunk is not: `main` in the code repo's checkout is the user's, and nothing
    updates it. Building on it puts a unit on a `main` from before its
    predecessor merged, so its review judges it against a group that no
    longer exists. The trunk is taken from the remote, which
    each tick fetches first; the PR's base stays the bare name GitHub knows.

    A repo with no remote (named by `repo`) has its own trunk to build on.
    """
    checkout = active_checkout(active().repos[repo].path) if repo is not None else None
    return build_ref(checkout, base)


def build_ref(checkout: Path | None, base: str) -> str:
    """The ref to build on for `base` in `checkout`, the one rule `local_ref` and the local
    forge share: a unit's branch, or the trunk of a checkout with no remote, as it is; the
    remote's trunk otherwise. No checkout is a repo with a remote."""
    if base.startswith(active().git.branch_prefix):
        return base
    if checkout is not None and not has_origin(checkout):
        return base
    return f"origin/{base}"


def plan_units(change: str, groups: list[dict], *, min_lines: int, max_lines: int) -> list[Unit]:
    """Group consecutive task groups into units.

    Absorbing continues until the estimate reaches `min_lines`, because a
    chain of small groups would otherwise become a stack of trivial PRs, each
    costing an issue, an e2e-test run, a restack and a merge. It stops early at a
    fan-out point — a group other units are waiting on — since finishing that
    sooner lets them start. It never combines groups past `max_lines`: a group
    that would take the unit over it starts a unit of its own.

    A unit never spans repos: a branch lives in one, so its unit does too. Nor does it span
    projects of one repo: a unit builds in one project.
    """
    units: list[Unit] = []
    current: list[dict] = []
    # The unit the next chained group depends on. An independent group is
    # outside the chain: it neither takes this tail nor moves it.
    tail: str | None = None
    # The independent units so far, which an acceptance or narrow unit depends on.
    standing: list[str] = []

    def flush() -> None:
        nonlocal tail
        if not current:
            return
        unit_id = f"{change}/{len(units) + 1}"
        alone = bool(current[0].get("independent"))
        # A group that exercises or removes what the others built depends on the end of
        # its chain and on each unit off it; the rest it reaches through the chain, and
        # `earlier_units` makes it wait for them at run time.
        joins_independent = current[0].get("flag") in ("acceptance", "narrow") and standing
        if alone:
            depends_on: tuple[str, ...] = ()
        elif joins_independent:
            depends_on = (*((tail,) if tail else ()), *standing)
        else:
            depends_on = (tail,) if tail else ()
        units.append(
            Unit(
                id=unit_id,
                change=change,
                title=current[0]["title"]
                if len(current) == 1
                else f"{current[0]['title']} (+{len(current) - 1})",
                repo=current[0]["repo"],
                project=current[0].get("project", "."),
                # A unit takes the widest kind of its groups: one that needs the live stack
                # anywhere needs it overall.
                tier=widest_kind(TestTier(new_spelling(Place.VALUE, g["tier"])) for g in current),
                estimated_lines=sum(g["estimated_lines"] for g in current),
                groups=tuple(g["number"] for g in current),
                depends_on=depends_on,
            )
        )
        if alone:
            standing.append(unit_id)
        else:
            tail = unit_id
        current.clear()

    for group in groups:
        independent = bool(group.get("independent"))
        # Joining is a form of ordering, so an independent group is joined
        # neither to the unit before it nor to the one after.
        if current and (
            independent
            or group["repo"] != current[0]["repo"]
            or group.get("project", ".") != current[0].get("project", ".")
        ):
            flush()

        size = sum(g["estimated_lines"] for g in current) + group["estimated_lines"]
        if current and size > max_lines:
            flush()
            size = group["estimated_lines"]

        current.append(group)

        if independent or group.get("fans_out") or size >= min_lines:
            flush()

    flush()
    return units


def _by_id(graph: Sequence[Unit]) -> dict[str, Unit]:
    return {unit.id: unit for unit in graph}


# How many replaced units `resolve_replaced` follows from one id.
REPLACED_DEPTH = 8


def successors_of(unit: Unit, units: Sequence[Unit]) -> tuple[str, ...]:
    """The ids of the units other than `unit` that build any `(change, group)` pair `unit`
    builds, own or joined, in id order. A unit that builds nothing or is closed does not
    carry them; a merged or satisfied one does, its work being covered."""
    pairs = carried_pairs(unit)
    return tuple(
        sorted(
            other.id
            for other in units
            if other.id != unit.id
            and other.state not in (*BUILDS_NOTHING, UnitState.CLOSED)
            and pairs & carried_pairs(other)
        )
    )


def carried_pairs(unit: Unit) -> set[tuple[str, int]]:
    """The (change, group) pairs the unit builds, its own and joined."""
    return {(member.change, number) for member in unit.members() for number in member.groups}


def _resolved(unit_id: str, index: dict[str, Unit]) -> tuple[str, ...]:
    def walk(uid: str, depth: int, seen: frozenset[str]) -> tuple[str, ...]:
        found = index.get(uid)
        if (
            found is None
            or found.state not in BUILDS_NOTHING
            or not found.superseded_by
            or depth >= REPLACED_DEPTH
        ):
            return (uid,)
        out: list[str] = []
        for successor in found.superseded_by:
            if successor not in seen and successor != uid:
                out.extend(walk(successor, depth + 1, seen | {uid}))
        return tuple(dict.fromkeys(out))

    return walk(unit_id, 0, frozenset()) or (unit_id,)


def resolve_replaced(unit_id: str, graph: Sequence[Unit]) -> tuple[str, ...]:
    """The ids that stand in for `unit_id`: itself, unless it is a replaced unit with
    successors, then theirs, followed through further replaced units (at most
    `REPLACED_DEPTH` links, cycle-safe), once each, in order."""
    return _resolved(unit_id, _by_id(graph))


def _current(unit: Unit, index: dict[str, Unit]) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            resolved
            for dep in unit.depends_on
            for resolved in _resolved(dep, index)
            if resolved != unit.id
        )
    )


def current_dependencies(unit: Unit, graph: Sequence[Unit]) -> tuple[str, ...]:
    """`unit.depends_on` with each entry that names a replaced unit read as the units that
    carry its work: de-duplicated, in order, never the unit itself. The one place a
    dependency is followed through `superseded_by`."""
    return _current(unit, _by_id(graph))


def through_satisfied(unit: Unit, graph: Sequence[Unit]) -> tuple[str, ...]:
    """`unit.depends_on`, with a same-repo `SATISFIED` dependency replaced by
    its own — recursively.

    A satisfied unit added no commits of its own: its branch, if it has one at
    all, is identical to whatever it was built on, and it never opened a PR.
    There is nothing there for a dependent to stack on, or for a merge or a
    restack to move — so anything that asks "what is this really built on"
    has to look straight through it to what *it* depended on. Used by
    `base_of` and `depth_of` here, and by `events._children_of` and
    `_dependents_of` to find a dependent stacked past a satisfied unit.

    A satisfied unit's cross-repo dependencies are passed up into the result
    alongside the same-repo ones they replace — every caller today filters
    the result by repo before using it, so this is harmless, but the result
    is not same-repo-only on its own.
    """
    index = _by_id(graph)

    def expand(dep_id: str, seen: frozenset[str]) -> tuple[str, ...]:
        if dep_id in seen:
            return ()
        parent = index.get(dep_id)
        if parent is None or parent.state != SATISFIED:
            return (dep_id,)
        seen = seen | {dep_id}
        out: list[str] = []
        for other in _current(parent, index):
            if other in index and index[other].repo == parent.repo:
                out.extend(expand(other, seen))
            else:
                out.append(other)
        return tuple(out)

    out: list[str] = []
    for dep in _current(unit, index):
        parent = index.get(dep)
        if parent is not None and parent.repo == unit.repo:
            out.extend(expand(dep, frozenset()))
        else:
            out.append(dep)
    return tuple(out)


def waiting_on_me(
    unit: Unit, graph: Sequence[Unit], excluded: Collection[str] = frozenset()
) -> list[Unit]:
    """The units that wait on `unit`, directly or through a chain, in any repo.

    The reverse of `depends_on`. A merged, closed or satisfied unit does not
    wait, though a satisfied one is looked through: what depends on it waits on
    what it was built on. Units in `excluded` (named away by `--only`, held by a
    lease or in a backoff) are not counted, but are looked through like a satisfied
    one: a unit in the round that waits through one still waits on `unit`.
    """
    dependents: dict[str, list[Unit]] = {}
    index = _by_id(graph)
    for other in graph:
        for dep in _current(other, index):
            dependents.setdefault(dep, []).append(other)

    found: dict[str, Unit] = {}
    visited = {unit.id}
    pending = [unit.id]
    while pending:
        for waiter in dependents.get(pending.pop(), ()):
            if waiter.id in visited:
                continue
            visited.add(waiter.id)
            if waiter.state == SATISFIED or waiter.id in excluded:
                pending.append(waiter.id)
            elif waiter.state not in (MERGED, CLOSED):
                found[waiter.id] = waiter
                pending.append(waiter.id)
    return list(found.values())


def effective_priority(
    unit: Unit, graph: Sequence[Unit], excluded: Collection[str] = frozenset()
) -> int:
    """The most urgent priority among `unit` and every unit waiting on it."""
    waiters = [waiter.priority for waiter in waiting_on_me(unit, graph, excluded)]
    return min([unit.priority, *waiters])


def priority_note(
    unit: Unit, graph: Sequence[Unit], excluded: Collection[str] = frozenset()
) -> str:
    """The unit's effective priority and its source; empty for a normal unit with none."""
    urgency = effective_priority(unit, graph, excluded)
    if urgency < unit.priority:
        source = min(
            waiting_on_me(unit, graph, excluded), key=lambda waiter: (waiter.priority, waiter.id)
        )
        return f"priority {urgency}, from {source.id}"
    if unit.promoted_from:
        return f"priority {urgency}, promoted from {unit.promoted_from}"
    return f"priority {urgency}" if urgency != Priority.NORMAL else ""


def stack_age_source(
    unit: Unit, graph: Sequence[Unit], excluded: Collection[str] = frozenset()
) -> Unit | None:
    """The oldest unit waiting on `unit`, when it was planned before `unit` itself.

    That unit is why `unit` starts at an older place than its own; None when
    nothing waiting on it is older.
    """
    position = {other.id: place for place, other in enumerate(graph)}
    oldest = min(
        waiting_on_me(unit, graph, excluded), key=lambda waiter: position[waiter.id], default=None
    )
    if oldest is not None and position[oldest.id] < position[unit.id]:
        return oldest
    return None


def effective_age(
    unit: Unit, graph: Sequence[Unit], excluded: Collection[str] = frozenset()
) -> int:
    """The earliest planned position among `unit` and every unit waiting on it.

    The planned position is the place in `graph`. Depth and the number of
    waiters do not count: only how long ago the oldest of them was planned.
    """
    source = stack_age_source(unit, graph, excluded) or unit
    return next(place for place, other in enumerate(graph) if other.id == source.id)


def trunk_of(repo: str) -> str:
    """The branch a repo's work lands on: what abk.yaml says, else `main`.

    This was a literal `main` in `base_of`, while `default_branch` was written
    into abk.yaml, documented as the branch units are built on, and read by the
    doctor. A repo that integrates on `dev` — one that `origin/HEAD` still says
    is `main` — therefore had every unit built on a branch that lacks the code
    it changes, and its pull requests proposed into the wrong place.

    A repo the workspace does not name gets `main`: it cannot be built anyway,
    and asking where it would start must not raise.
    """
    entry = active().repos.get(repo)
    return entry.default_branch if entry is not None else "main"


def base_of(unit: Unit, graph: Sequence[Unit]) -> str:
    """The branch this unit builds on.

    Its newest still-open dependency in the same repo (`_stack_base`: the one the
    others are built on, else the deepest, a tie going to the later in plan order),
    for a unit that has started as for one that has not, whatever order the
    dependencies are listed in. With none open, the repo's default branch. Nothing
    starts from the trunk by default: if the work it needs is in flight, stacking
    on it is what keeps the two from duplicating or conflicting.

    A same-repo dependency that is satisfied is transparent (see
    `through_satisfied`): it has no branch of its own, so its dependent stacks
    on whatever it depended on instead — its still-open predecessor, or `main`
    once that predecessor has also merged.

    A cross-repo dependency is never a base — stacks can't span repos, so that
    edge is an ordering constraint instead, and `ready_units` makes the
    dependent wait for a merge.
    """
    base = _stack_base(unit, graph)
    return branch_name(base) if base is not None else trunk_of(unit.repo)


def open_parents(unit: Unit, graph: Sequence[Unit]) -> list[Unit]:
    """The same-repo dependencies of `unit` that are in review, looked through satisfied ones,
    in plan order."""
    index = _by_id(graph)
    wanted = {
        dep
        for dep in through_satisfied(unit, graph)
        if dep in index and index[dep].repo == unit.repo and index[dep].state == IN_REVIEW
    }
    return [parent for parent in graph if parent.id in wanted]


def reachable[T](start: Iterable[T], successors: Callable[[T], Iterable[T]]) -> set[T]:
    """Everything reached from `start` by following `successors`, however far; a `seen` set
    ends the walk of a stored cycle."""
    seen: set[T] = set()
    pending = list(start)
    while pending:
        node = pending.pop()
        if node not in seen:
            seen.add(node)
            pending.extend(successors(node))
    return seen


def direct_dependencies(unit: Unit, graph: Sequence[Unit]) -> tuple[str, ...]:
    """`unit.depends_on`, in its stored order, without a dependency another of them reaches.

    The walk follows stored `depends_on` edges through units of every state and repo, and does
    not look through a satisfied unit. Two dependencies that reach each other (a stored cycle)
    are both kept.
    """
    index = _by_id(graph)

    def successors(uid: str) -> tuple[str, ...]:
        return index[uid].depends_on if uid in index else ()

    reach = {dep: reachable(successors(dep), successors) for dep in unit.depends_on}
    return tuple(
        dep
        for dep in unit.depends_on
        if not any(
            other != dep and dep in reach[other] and other not in reach[dep]
            for other in unit.depends_on
        )
    )


def as_shown[U: Unit](unit: U, graph: Sequence[Unit]) -> U:
    """`unit` as a view shows it: its dependencies read through `superseded_by`
    (`current_dependencies`) and cut to the direct ones."""
    current = unit.model_copy(update={"depends_on": current_dependencies(unit, graph)})
    return current.model_copy(update={"depends_on": direct_dependencies(current, graph)})


def shown_dependencies(unit: Unit, graph: Sequence[Unit]) -> tuple[str, ...]:
    """The dependencies a view shows for `unit`."""
    return as_shown(unit, graph).depends_on


def shown_waits(unit: Unit, graph: Sequence[Unit]) -> list[Unit]:
    """What `unit` waits on, asked of the unit as a view shows it, so a wait names only
    dependencies the views draw and list."""
    return waiting_on(as_shown(unit, graph), graph)


def repointed[U: Unit](units: Mapping[str, U], taken: str, onto: str) -> dict[str, U]:
    """The units that depended on `taken`, depending on `onto` instead, each list
    de-duplicated and reduced over the graph with `taken` gone."""
    moved = {
        uid: unit.model_copy(
            update={
                "depends_on": tuple(
                    dict.fromkeys(onto if d == taken else d for d in unit.depends_on)
                )
            }
        )
        for uid, unit in units.items()
        if taken in unit.depends_on
    }
    graph = [*(u for uid, u in units.items() if uid not in moved), *moved.values()]
    return {
        uid: unit.model_copy(update={"depends_on": direct_dependencies(unit, graph)})
        for uid, unit in moved.items()
    }


def _builds_on(unit: Unit, graph: Sequence[Unit]) -> set[str]:
    """Every unit `unit` is built on, however far, through `through_satisfied`."""
    index = _by_id(graph)
    return reachable(
        through_satisfied(unit, graph),
        lambda dep: through_satisfied(index[dep], graph) if dep in index else (),
    )


def unrelated_open_parents(unit: Unit, graph: Sequence[Unit]) -> list[Unit]:
    """The open parents of `unit` that no other open parent builds on, in plan order."""
    parents = open_parents(unit, graph)
    built_on: set[str] = set()
    for parent in parents:
        built_on |= _builds_on(parent, graph)
    return [parent for parent in parents if parent.id not in built_on]


def _stack_base(unit: Unit, graph: Sequence[Unit]) -> Unit | None:
    """The unrelated open parent `unit` builds on: the deepest, a tie going to the later."""
    unrelated = unrelated_open_parents(unit, graph)
    if not unrelated:
        return None
    return max(enumerate(unrelated), key=lambda item: (depth_of(item[1], graph), item[0]))[1]


def second_open_parents(unit: Unit, graph: Sequence[Unit]) -> list[Unit]:
    """The unrelated open parents a planned unit that has never started waits for besides its
    base. A unit that has started keeps the branch it is on, so waits for none."""
    if unit.state != PLANNED or _worked_on(unit):
        return []
    base = _stack_base(unit, graph)
    return [parent for parent in unrelated_open_parents(unit, graph) if parent is not base]


def second_parent_wait(unit: Unit, graph: Sequence[Unit]) -> str:
    """What a unit waits for as a second open parent, in a person's words; "" when it does not."""
    parents = second_open_parents(unit, graph)
    if not parents:
        return ""
    return f"waiting for {group_names(parents)} to merge (second open parent)"


def depth_of(unit: Unit, graph: Sequence[Unit]) -> int:
    """Length of the longest chain of open ancestors, counting this unit.

    Merged ancestors drop out, which is what makes merging the bottom PR free
    a layer for everything above it. Siblings on a shared base share a depth
    rather than adding to it: a stack is a tree, not a line. A satisfied
    ancestor is transparent, the same as in `base_of`: it adds no layer of its
    own, so the chain is counted through it to its own open ancestors.
    """
    index = _by_id(graph)

    def walk(current: Unit, seen: frozenset[str]) -> int:
        open_parents = [
            index[dep]
            for dep in through_satisfied(current, graph)
            if dep in index
            and dep not in seen
            and index[dep].repo == current.repo
            and index[dep].state == IN_REVIEW
        ]
        if not open_parents:
            return 1
        return 1 + max(walk(parent, seen | {current.id}) for parent in open_parents)

    return walk(unit, frozenset())


def satisfied_landed(unit: Unit, graph: Sequence[Unit]) -> bool:
    """Whether a satisfied unit's own work has actually reached the trunk.

    A satisfied unit never merges — it added nothing, so it never opened a
    PR — so whatever must otherwise wait for an actual merge (a cross-repo
    dependent, which cannot stack on it, or the archiving of its change) is
    released once the same-repo predecessor whose branch already carried the
    work has itself merged. No same-repo dependency at all means there was
    never anywhere else for the work to land, so it counts as landed already.
    """
    index = _by_id(graph)

    def landed(current: Unit, seen: frozenset[str]) -> bool:
        same_repo = [
            index[dep]
            for dep in _current(current, index)
            if dep in index and index[dep].repo == current.repo and dep not in seen
        ]
        return all(
            dep.state == MERGED or (dep.state == SATISFIED and landed(dep, seen | {current.id}))
            for dep in same_repo
        )

    return landed(unit, frozenset())


_ID_TAIL = re.compile(r"(?P<number>\d+)(?P<suffix>(?:-s\d+)*)")


def unit_id_parts(unit_id: str) -> tuple[int, str]:
    """The integer after the change in a `<change>/<n>` id, and the `-s<k>` suffix a piece of a
    split adds to its parent's id (`""` for an ordinary id). The one place an id is taken apart."""
    tail = _ID_TAIL.fullmatch(unit_id.rsplit("/", 1)[1])
    if tail is None:
        raise ValueError(f"not a unit id: {unit_id}")
    return int(tail["number"]), tail["suffix"]


def unit_file_prefix(unit_id: str, change: str | None = None) -> str:
    """The start of the names of a unit's run logs and transcripts, `<change>-<nn><suffix>-`
    (the change is the id's own unless given), which a timestamp follows directly. A piece of a
    split has its suffix in it, so no unit's files are matched by another's prefix."""
    number, suffix = unit_id_parts(unit_id)
    return f"{change if change is not None else unit_id.rsplit('/', 1)[0]}-{number:02d}{suffix}-"


def unit_number(unit: Unit) -> int:
    """The `<n>` of a unit's `<change>/<n>` id: its place in its change's plan order. A piece
    of a split sorts where its root did."""
    return unit_id_parts(unit.id)[0]


def earlier_units(unit: Unit, graph: Sequence[Unit]) -> list[Unit]:
    """The units an acceptance or narrow `unit` follows beyond its stored dependencies: every
    unit of its own change numbered before it that the plan has not dropped and a split has not
    replaced (the pieces are followed instead). Computed from the
    change's units each time, so it needs no stored edge; a unit with no flag follows only the
    chain and has none."""
    if getattr(unit, "flag", "") not in ("acceptance", "narrow"):
        return []
    number = unit_number(unit)
    return [
        other
        for other in graph
        if other.change == unit.change
        and other.id != unit.id
        and other.state not in BUILDS_NOTHING
        and not is_superseded(other)
        and unit_number(other) < number
    ]


def followed_dependencies(unit: Unit, graph: Sequence[Unit]) -> list[str]:
    """The ids `unit` waits on, stops for and follows: its stored dependencies looked through
    satisfied units (`through_satisfied`), then the earlier units of its change
    (`earlier_units`) not already among them. The one place the two are joined."""
    stored = through_satisfied(unit, graph)
    return [*stored, *(other.id for other in earlier_units(unit, graph) if other.id not in stored)]


class EdgeKind(StrEnum):
    """What a dependency edge waits for: the parent being in review, or being merged and loaded."""

    REVIEW = "review"
    MERGE = "merge"


class Edge(Frozen):
    """The kind of one dependency edge and, for a merge edge, why it is one."""

    kind: EdgeKind
    reason: str = ""


# The prefix of the change the pipeline writes for a product defect a live test found.
PRODUCT_DEFECT_PREFIX = "fix-product-defect"


def edge_kind(unit: Unit, parent: Unit, repos: Mapping[str, RepoConfig]) -> Edge:
    """The kind of the edge from `unit` to its parent `parent` (`repos` is the workspace's repos,
    kept in the signature for a rule that needs one; none does yet): a merge edge when it crosses
    repositories, when the author wrote `merged`, or when `unit` is a failed unit waiting (or
    one requeued while it waited), except that a unit parked on the fix of a product defect it
    reported goes on once that fix is in review; otherwise a review edge."""
    if parent.repo != unit.repo:
        return Edge(kind=EdgeKind.MERGE, reason="another repository")
    if parent.id in unit.merge_needs:
        return Edge(kind=EdgeKind.MERGE, reason="the Needs: line says merged")
    if parent.change.startswith(f"{PRODUCT_DEFECT_PREFIX}-") and parent.change != unit.change:
        return Edge(kind=EdgeKind.REVIEW)
    if unit.state == FAILED or (
        unit.state == PLANNED and getattr(unit, "gated_requeue", None) is not None
    ):
        return Edge(kind=EdgeKind.MERGE, reason="a failed unit resumes after the fix is merged")
    return Edge(kind=EdgeKind.REVIEW)


def parent_landed(parent: Unit, graph: Sequence[Unit]) -> bool:
    """Whether `parent` is merged, or satisfied with its work landed."""
    return parent.state == MERGED or (parent.state == SATISFIED and satisfied_landed(parent, graph))


def _merge_missing(parent: Unit, graph: Sequence[Unit], loaded: LoadedCode | None) -> str:
    """What a merge wait on `parent` is for: its merge, the next tick that loads it, or the kit
    checkout to include it."""
    names = group_names([parent])
    if not parent_landed(parent, graph):
        return f"{names} to merge"
    sha = getattr(parent, "merge_sha", None)
    if (
        loaded is not None
        and sha is not None
        and parent.repo == loaded.kit_repo
        and loaded.contains(sha) is False
        and not loaded.checkout_contains(sha)
    ):
        return f"the kit checkout to include {names}'s merge"
    return f"the next tick to load {names}'s merge"


def merge_parents(
    unit: Unit, parents: Sequence[Unit], graph: Sequence[Unit], repos: Mapping[str, RepoConfig]
) -> dict[str, str]:
    """For each of `parents` that `unit` has a merge edge to, what it waits for and why the edge
    is a merge edge, as `dependency_wait` words it (keyed by the parent's id)."""
    loaded = loaded_code.current()
    found: dict[str, str] = {}
    for parent in parents:
        edge = edge_kind(unit, parent, repos)
        if edge.kind is EdgeKind.MERGE:
            found[parent.id] = f"{_merge_missing(parent, graph, loaded)} (merge: {edge.reason})"
    return found


def merge_loaded(parent: Unit, graph: Sequence[Unit], loaded: LoadedCode) -> bool:
    """Whether the merge of `parent` (looked through satisfied units to the merges they were
    built on) is in the code the tick runs.

    A merge with no record (merged before it was kept) counts as loaded. In the kit's own
    repository the merge commit must be in the recorded head; otherwise, or when the head or
    the commit is unknown, the tick must be a later one than the tick that saw the merge."""
    index = _by_id(graph)

    def one(current: Unit, seen: frozenset[str]) -> bool:
        if current.state == SATISFIED:
            return all(
                one(index[dep], seen | {current.id})
                for dep in _current(current, index)
                if dep in index and index[dep].repo == current.repo and dep not in seen
            )
        sha = getattr(current, "merge_sha", None)
        tick = getattr(current, "merged_tick", None)
        if sha is None and tick is None:
            return True
        if sha is not None and current.repo == loaded.kit_repo:
            held = loaded.contains(sha)
            if held is not None:
                return held
        return tick is None or loaded.number > tick

    return one(parent, frozenset())


def is_superseded(unit: Unit) -> bool:
    """Whether the unit was replaced by the pieces of a split: closed, with `superseded_by`
    naming them. It is finished without merging, and its pieces carry its groups."""
    return unit.state == UnitState.CLOSED and bool(unit.superseded_by)


def waiting_on(unit: Unit, graph: Sequence[Unit], loaded: LoadedCode | None = None) -> list[Unit]:
    """The dependencies that stop `unit` starting now.

    Same-repo ones must be complete — through the build/review loop, so there
    is a reviewed branch to stack on. A satisfied one is looked through
    (`through_satisfied`), as `base_of` does: it has no branch of its own, so
    what `unit` waits on is what that dependency was built on. Its predecessor
    sent back for rework, or failed, holds `unit` too; in review or merged it
    does not. Cross-repo ones must have merged: the dependent can't stack on
    them, so it waits rather than building against a moving target — except a
    satisfied cross-repo dependency, which never merges itself; it is done
    once its own same-repo work has (`satisfied_landed`). The scheduler and
    the diagram both ask this, so the graph never shows a unit as startable
    that the tick would hold back.

    A planned unit that has never started also waits for all but one of its
    unrelated open parents (`second_open_parents`): it cannot build on two
    branches, so it builds on one and waits for the others.

    An acceptance or narrow unit also waits for every earlier unit of its change
    (`earlier_units`), by the rule a dependency on it would have; that adds waits
    only, and leaves its base, depth and open parents to its stored dependencies.

    A merge edge (`edge_kind`) holds `unit` until its parent has merged (or is satisfied with its
    work landed) and, given the code the tick runs (`loaded`, by default the last tick's record;
    no record holds nothing more), that merge is in it (`merge_loaded`). That covers a `Needs:`
    target that is not among the stored dependencies too.
    """
    index = _by_id(graph)
    waiting: list[Unit] = []
    repos = active().repos
    if loaded is None:
        loaded = loaded_code.current()

    followed = followed_dependencies(unit, graph)
    for dep in [*followed, *(dep for dep in unit.merge_needs if dep not in followed)]:
        parent = index.get(dep)
        # A unit the plan dropped builds nothing, so nothing waits on it.
        if (
            parent is None
            or parent.state in BUILDS_NOTHING
            or is_superseded(parent)
            or parent in waiting
        ):
            continue
        if edge_kind(unit, parent, repos).kind is EdgeKind.MERGE:
            # A closed parent will never merge: a failed unit's wait is over (it ends as closed).
            if parent.state == CLOSED and unit.state == FAILED:
                continue
            if not parent_landed(parent, graph) or (
                loaded and not merge_loaded(parent, graph, loaded)
            ):
                waiting.append(parent)
        elif parent.state not in REVIEWED:
            waiting.append(parent)
    waiting.extend(second_open_parents(unit, graph))
    return waiting


# The causes a unit carries from a wait on another unit; they stay on its record
# after the wait ends, which is how a unit that was blocked is told from one that
# was merely interrupted.
_WAIT_CAUSES = ("gated", "upstream_went_back")

# The cause of a planned unit parked for held e2e-test splits (`Cause.SPLIT_HELD`'s value).
SPLIT_HELD_CAUSE = "split_held"


# The cause of a planned unit parked for a manual step (`Cause.MANUAL_STEP`'s value).
MANUAL_STEP_CAUSE = "manual_step"


def parked_for_manual_step(unit: Unit) -> bool:
    """Whether a planned unit is parked for a step only a person can do. It keeps its place,
    as any started unit does, and is not started again until the tick has readmitted it."""
    return unit.state == PLANNED and getattr(unit, "cause", None) == MANUAL_STEP_CAUSE


def parked_on_split(unit: Unit) -> bool:
    """Whether a planned or unplanned unit waits on a held e2e-test split, so it holds no place.

    A planned unit with the cause `split_held` does, as does one with `parked_splits` whose
    latest cause is not another (a state change that records no cause loses `split_held`;
    a requeue or interruption after the park puts the unit on its way to run).
    """
    if unit.state not in (PLANNED, UnitState.UNPLANNED):
        return False
    cause = getattr(unit, "cause", None)
    # The cause is standing, so a replan carries it and this reads the same after one.
    if unit.state == PLANNED and cause == SPLIT_HELD_CAUSE:
        return True
    return bool(getattr(unit, "parked_splits", None)) and cause in (None, SPLIT_HELD_CAUSE)


def blocked(unit: Unit, graph: Sequence[Unit]) -> bool:
    """Whether a planned unit waits on another unit, so it holds no place.

    It waits on a dependency or a predecessor that has not been reviewed or
    merged, or that is being reworked, failed or held (`waiting_on`): a gate not
    yet merged and an upstream that went back are both waits of that kind, and
    end with them. A backoff, a lease, a limited tick and a usage pause are not
    waits on another unit. Derived from the units each time, as `waiting_on` is.
    """
    return unit.state == PLANNED and bool(waiting_on(unit, graph))


def dependency_wait(units: Sequence[Unit], *, merging: Mapping[str, str] = {}) -> str:
    """What a unit held by these dependencies is waiting for, in a person's words.

    A dependency the unit has a merge edge to is named by `merging` (`merge_parents`): what is
    missing of its merge and why the edge is one; any other only by its task group."""
    names = [merging.get(unit.id) or group_names([unit]) for unit in units]
    return f"waiting for {', '.join(names)}"


def group_names(units: Sequence[Unit]) -> str:
    """The task groups of these units, as a person reads them in a `Needs:` line."""
    return ", ".join(
        f"{unit.change} group {', '.join(str(group) for group in unit.groups)}".rstrip()
        for unit in units
    )


def later_groups(unit: Unit, graph: Sequence[Unit]) -> tuple[int, ...]:
    """Task groups of this change that belong to units after this one.

    Group numbers only increase through `tasks.md`, so anything above this
    unit's own highest group is later work — whichever unit the plan gave it
    to, and whether or not that unit has run yet.

    Not a unit the plan has since dropped: "unplanned" (`unit_store.UNPLANNED`,
    named here as a literal to avoid importing the store into this module —
    `archive.py` does the same) is not going to build its groups, so naming
    them as belonging to a later unit would leave them looking spoken for when
    nothing is going to touch them.
    """
    return later_groups_by_change(unit, graph).get(unit.change, ())


def later_groups_by_change(unit: Unit, graph: Sequence[Unit]) -> dict[str, tuple[int, ...]]:
    """`later_groups` for every change the unit builds groups of.

    A group the unit carries is its own work, not later work, so only groups
    above each change's highest one this unit builds, in other units, count.
    """
    # A chain of joins can give one change several members, so the ceiling is
    # taken across all of them, not per member.
    mine: dict[str, set[int]] = {}
    for member in unit.members():
        mine.setdefault(member.change, set()).update(member.groups)
    later: dict[str, tuple[int, ...]] = {}
    for change, own in mine.items():
        ceiling = max(own, default=0)
        others = {
            group
            for other in graph
            if other.id != unit.id and other.state not in BUILDS_NOTHING
            for carried in other.members()
            if carried.change == change
            for group in carried.groups
            if group > ceiling and group not in own
        }
        if others:
            later[change] = tuple(sorted(others))
    return later


def in_progress(unit: Unit, graph: Sequence[Unit] = ()) -> bool:
    """Whether the unit has been started and not finished (docs/architecture.md).

    A planned or unplanned unit parked on a held e2e-test split (`parked_on_split`) is
    not, whatever its cause field says and whatever work it has: it has nothing to run
    until the split is released. An unplanned one is left alone on release, because the
    plan no longer has it, and stays uncounted until a replan plans it again; a replan
    keeps the park.

    Running, in review and failed units are; so is a planned or unplanned one
    that has a pull request, a branch or a pushed commit, since something was
    already done to it: a run records its branch when it begins, so a unit held
    before a step, or whose branch a person pushed, shows it. Merged, closed
    and satisfied units are finished, and a unit with no pull request, branch
    or pushed commit has never started, blocked on a dependency or not.

    A held unit is not: holding takes a unit out of the automatic flow until a
    person releases it, whether a reviewer, the review loop or the operator
    held it, and a unit set aside that way should not keep new work from
    starting. Requeued, it counts again from its next start.

    A blocked planned unit (`blocked`, judged against `graph`) does not count
    however much work it has, and counts again when it is no longer blocked. A
    failed unit that waits on another unit (`failed_waiting`) does not count
    while it waits, and stays failed.
    """
    if unit.state in (MERGED, CLOSED, SATISFIED, HELD, UnitState.RETIRED):
        return False
    if unit.state == FAILED:
        return not failed_waiting(unit, graph)
    if unit.state in (RUNNING, IN_REVIEW, SETTLING):
        return True
    if parked_on_split(unit):
        return False
    return _worked_on(unit) and not blocked(unit, graph)


def uncounted(graph: Sequence[Unit]) -> list[Unit]:
    """The blocked units that have work, so would count were they not blocked."""
    return [unit for unit in graph if blocked(unit, graph) and _worked_on(unit)]


def failed_waiting(unit: Unit, graph: Sequence[Unit]) -> bool:
    """Whether a failed unit waits on another unit (`waiting_on`), so it holds no place."""
    return unit.state == FAILED and bool(waiting_on(unit, graph))


def failed_waiting_units(graph: Sequence[Unit]) -> list[Unit]:
    """The failed units that wait on another unit and so are not counted."""
    return [unit for unit in graph if failed_waiting(unit, graph)]


def _waits_for_room(unit: Unit, graph: Sequence[Unit]) -> bool:
    """Whether a planned unit that was blocked, and no longer is, must wait for
    room: it has work and no pull request, and either its record still carries
    the cause of the wait it left, or a unit it depends on was outside review
    and merge at some point since the unit last changed state (`_parent_went_back`).
    A build interrupted by a usage pause, a backoff or a lease, whose parents stayed
    reviewed or merged throughout, resumes at the limit."""
    # The cause is standing, so a replan carries it and this reads the same after one.
    return (
        unit.state == PLANNED
        and in_progress(unit, graph)
        and getattr(unit, "pr", None) is None
        and (getattr(unit, "cause", None) in _WAIT_CAUSES or _parent_went_back(unit, graph))
    )


def history_stamp(entry: dict[str, object]) -> datetime | None:
    """When a history entry was made, or None when it carries no readable time."""
    try:
        return datetime.fromisoformat(str(entry.get("at", "")))
    except ValueError:
        return None


def _parent_went_back(unit: Unit, graph: Sequence[Unit]) -> bool:
    """Whether a unit `unit` depends on was neither reviewed nor merged at the
    moment of its last state change, or at any time after it: the unit was
    blocked since it last ran, whatever cause its record carries. Read from the
    parents' recorded history, as nothing writes a cause on a paused unit whose
    predecessor went back after it stopped."""
    own = [stamp for entry in getattr(unit, "history", ()) if (stamp := history_stamp(entry))]
    since = own[-1] if own else None
    index = _by_id(graph)
    for dep in through_satisfied(unit, graph):
        parent = index.get(dep)
        if parent is None or parent.state in BUILDS_NOTHING:
            continue
        state_then: str | None = None
        for entry in getattr(parent, "history", ()):
            stamp = history_stamp(entry)
            if stamp is None:
                continue
            try:
                later = since is None or stamp >= since
            except TypeError:
                continue
            if later:
                if entry.get("state") not in REVIEWED:
                    return True
            else:
                state_then = str(entry.get("state"))
        if state_then is not None and state_then not in REVIEWED:
            return True
    return False


def _worked_on(unit: Unit) -> bool:
    """Whether a run has already done something to the unit: the graph records
    its branch when a run begins, then the pushed and approved commits."""
    return (
        getattr(unit, "pr", None) is not None
        or bool(getattr(unit, "branch", ""))
        or bool(getattr(unit, "pushed", None))
        or bool(getattr(unit, "approved", ""))
    )


def in_progress_label(unit: Unit, *, parked: Collection[str] = ()) -> str:
    """Why an in-progress unit counts, for the report of a full queue.

    A planned or unplanned unit is in progress only because something was
    already done to it, so it is named for that, not `planned`: "reworking"
    with a pull request, "paused" with only a branch of work. A unit in `parked`
    (the started units a pause holds) is "paused" whatever its state.
    """
    if unit.id in parked:
        return "paused"
    if unit.state in (PLANNED, UnitState.UNPLANNED):
        return "reworking" if getattr(unit, "pr", None) is not None else "paused"
    if unit.state == FAILED and getattr(unit, "cause", None) == "environment":
        return "waiting for the environment"
    return unit.state.replace("_", " ")


# Stands for every slot where a slot key is asked for; None is a key too, the default account's.
EVERY_SLOT = object()


def start_room(
    graph: Sequence[Unit],
    limit: int,
    project: Hashable = EVERY_SLOT,
    slot_of: Callable[[Unit], Hashable] = project_key,
) -> int:
    """How many never-started units may begin before `limit` is reached, in `project` (a slot of
    `slot_of`; every unit counts when `EVERY_SLOT`)."""
    counts = project_counts(graph, slot_of)
    return room_left(
        limit, sum(counts.values()) if project is EVERY_SLOT else counts.get(project, 0)
    )


def room_left(limit: int, counted: int) -> int:
    """How many more units may begin when `counted` are counted against `limit`."""
    return max(0, limit - counted)


def _start_rank(unit: Unit) -> int:
    """Existing work first: an open pull request, then a paused build, then new."""
    if getattr(unit, "pr", None) is not None:
        return 0
    return 1 if _worked_on(unit) else 2


def _start_key(
    unit: Unit, graph: Sequence[Unit], excluded: Collection[str], handed_off: Collection[str]
) -> tuple[int, ...]:
    """The sort key of a ready unit; the sort is stable, so ties keep planned order.

    New units go by effective priority, then handoff units before the others of
    equal priority, then effective age.
    """
    rank = _start_rank(unit)
    urgency = effective_priority(unit, graph, excluded)
    if rank < 2:
        return (rank, urgency)
    return (rank, urgency, 0 if unit.id in handed_off else 1, effective_age(unit, graph, excluded))


def start_order[U: Unit](
    units: Sequence[U], graph: Sequence[Unit], excluded: Collection[str] = ()
) -> list[U]:
    """`units` in the order starts are chosen: existing work first, then by effective priority.
    Units waiting to resume are taken in this order, so a free worker goes to the first of them
    and not to the first the store lists."""
    return sorted(units, key=lambda unit: _start_key(unit, graph, excluded, ())[:2])


def handoff_units(
    ready: Sequence[Unit], graph: Sequence[Unit], excluded: Collection[str]
) -> list[Unit]:
    """The ready units that take the places of blocked units, in the order to start them.

    Each blocked unit that has work and would otherwise count frees one place,
    and each place goes to one ready unit that has never run and that the blocked
    unit waits on; one that several blocked units wait on takes one place. Several
    are ordered by effective priority, then effective age. `ready_units` sorts
    them among the other ready units, ahead of those of equal priority only.
    """
    freed = {unit.id for unit in uncounted(graph)}
    chosen: list[Unit] = []
    for unit in sorted(
        (unit for unit in ready if _start_rank(unit) == 2),
        key=lambda unit: _start_key(unit, graph, excluded, ()),
    ):
        waiters = [w.id for w in waiting_on_me(unit, graph, excluded) if w.id in freed]
        if waiters:
            freed.discard(waiters[0])
            chosen.append(unit)
    return chosen


def emergency_start(unit: Unit, graph: Sequence[Unit], excluded: Collection[str]) -> bool:
    """Whether a planned unit may start in the emergency lane: it has never started, or waits
    for room as a new unit does (`_waits_for_room`), and its effective priority is 0, its
    own or lent by a unit that waits on it. A unit already in progress (a rework, a resume)
    is not: it draws on no place, and keeps to the workers."""
    return (not in_progress(unit, graph) or _waits_for_room(unit, graph)) and effective_priority(
        unit, graph, excluded
    ) == 0


def ready_units(
    graph: Sequence[Unit],
    *,
    max_concurrent: int,
    depth_cap: int,
    max_units_in_progress: int | None = None,
    excluded: Collection[str] = frozenset(),
    emergency_extra: int = 0,
    in_lane: Collection[str] = frozenset(),
    extra_workers: Mapping[ProjectKey, int] | None = None,
    slot_of: Callable[[Unit], Hashable] = project_key,
    slot_limit: Callable[[Hashable], int] | None = None,
    no_worker: Collection[str] = frozenset(),
) -> list[Unit]:
    """The planned units that may start right now, in the order to start them.

    A unit is ready when every dependency allows it: same-repo dependencies
    may be open (it stacks on them), cross-repo ones must have merged. A
    satisfied dependency is looked through to what it was built on, so a unit
    is not ready while that predecessor is still being built, failed or held. The
    depth cap then holds back chains that have run too far ahead of review
    without touching their siblings, and the concurrency cap limits how many
    units of one project are being built at once.

    `max_units_in_progress` bounds the units started and not finished in each
    project (repo and project, `project_key`; `in_progress`), never in total; `slot_of` and
    `slot_limit` count them under another key instead, an account, each with its own limit. A
    unit that has never started begins only while that leaves room in its own
    project, and no more of them than it does; one already in progress (a
    rework, a resume, a unit finishing its review loop) always may, since
    running it is how the queue drains. A ready unit of a full project, or of
    one with no free slot, is skipped and the next ready unit is considered.

    Free slots go to units with an open pull request, then to those resuming
    a build, then to new ones; within each, the most urgent effective priority
    first, then the order they were planned. New ones, between equal priorities,
    put handoff units (`handoff_units`) first, then go by effective age (the
    earliest planned position among the unit and every unit waiting on it), then
    their own planned position. A handoff unit never goes ahead of a more urgent
    one; it still takes the place a blocked unit frees when nothing more urgent can.
    `excluded` names the units the round leaves out, which lend no priority to what they wait on.

    A unit that could start (`emergency_start`) with priority 0 starts even where the project
    is full, in places or in workers, while the units of the project's emergency lane
    (`in_lane`, the ids; one still in progress uses the lane) number fewer than
    `emergency_extra`. It takes no place or worker from the count of the units after it, and
    the lane's units count as in progress and running for the units that have never started,
    so ordinary starts wait; a unit already started is held to the workers without them.
    `extra_workers` adds workers to `max_concurrent` for the projects it names and no other.
    `no_worker` names running units no run holds (a unit paused for usage): they are in progress
    and hold a place of the limit, and they take no worker.
    """
    running = count_by_project(
        graph, lambda unit: unit.state == RUNNING and unit.id not in no_worker
    )

    # A unit that was blocked and no longer is draws on the room like a new one.
    counted = count_by(
        graph,
        slot_of,
        lambda unit: in_progress(unit, graph) and not _waits_for_room(unit, graph),
    )

    ready: list[Unit] = []
    for unit in graph:
        if unit.state != PLANNED or parked_for_manual_step(unit):
            continue

        if waiting_on(unit, graph):
            continue

        if depth_of(unit, graph) > depth_cap:
            continue

        ready.append(unit)

    handed_off = {unit.id for unit in handoff_units(ready, graph, excluded)}
    ordered = sorted(ready, key=lambda unit: _start_key(unit, graph, excluded, handed_off))

    lane_use = count_by_project(graph, lambda unit: unit.id in in_lane and in_progress(unit, graph))
    # A paused unit in the lane is in `no_worker`: it is not in `running`, so it is not taken
    # off it either.
    lane_running = count_by_project(
        graph,
        lambda unit: unit.id in in_lane and unit.state == RUNNING and unit.id not in no_worker,
    )
    started: list[Unit] = []
    taken: dict[ProjectKey, int] = {}
    drawn: dict[Hashable, int] = {}
    for unit in ordered:
        key = project_key(unit)
        slot = slot_of(unit)
        limit = slot_limit(slot) if slot_limit else max_units_in_progress
        new = not in_progress(unit, graph) or _waits_for_room(unit, graph)
        draws = max_units_in_progress is not None and new
        # A unit already started is held to the workers the lane's units leave.
        busy = running.get(key, 0) - (0 if new else lane_running.get(key, 0))
        room = max_concurrent + (extra_workers or {}).get(key, 0)
        if busy + taken.get(key, 0) >= room or (
            draws and counted.get(slot, 0) + drawn.get(slot, 0) >= (limit or 0)
        ):
            if lane_use.get(key, 0) < emergency_extra and emergency_start(unit, graph, excluded):
                lane_use[key] = lane_use.get(key, 0) + 1
                started.append(unit)
            continue
        if draws:
            drawn[slot] = drawn.get(slot, 0) + 1
        taken[key] = taken.get(key, 0) + 1
        started.append(unit)
    return started
