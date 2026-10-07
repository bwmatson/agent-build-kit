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

from collections.abc import Sequence
from enum import StrEnum
from typing import Self

from agent_build_kit.config import active
from agent_build_kit.model import Frozen

# States a unit moves through. "running" means it is in the build/review loop:
# a worktree is open and an agent is working. "in_review" means the loop has
# passed and its PR is waiting for a human. It was called "open", after the
# PR's GitHub state, which read as unfinished for a unit that was done with
# everything the pipeline does to it (see unit_store).
PLANNED = "planned"
RUNNING = "running"
IN_REVIEW = "in_review"
MERGED = "merged"
CLOSED = "closed"

# Stopped on something it could not get past; its feedback says what. Nothing
# retries it until someone requeues it (`abk requeue`).
FAILED = "failed"

# The pipeline is keeping its hands off this unit: a reviewer asked it to, the
# toolchain cannot build it, or a merge left it beyond the rebase cap (which a
# later merge releases). Not a lifecycle state like the ones above: those
# describe how far a unit has got, and this describes who is driving it.
HELD = "held"

# A unit whose groups needed nothing: it added no commits of its own, and what
# was already at the tip passed tier 1. There is no diff, so no PR and nothing
# to review — the work arrived by another unit building ahead of its plan.
SATISFIED = "satisfied"

IN_FLIGHT = (RUNNING, IN_REVIEW)

# What a dependent may build on. A unit is not finished when it starts — it is
# finished when it has passed the build/review loop and tier 1 and been pushed,
# which is what `in_review` means. `IN_FLIGHT` includes `running`, so using it here
# unblocked a dependent the moment its parent *began*, against a branch nothing
# had reviewed and which might not exist yet. The review loop, which can send a
# unit back three times, makes that window much wider. A satisfied unit belongs
# here too: it has nothing left to do and nothing that will change under it.
REVIEWED = (IN_REVIEW, MERGED, SATISFIED)


class UnitState(StrEnum):
    PLANNED = "planned"
    RUNNING = "running"
    IN_REVIEW = "in_review"
    MERGED = "merged"
    CLOSED = "closed"
    FAILED = "failed"
    HELD = "held"
    SATISFIED = "satisfied"


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


class Unit(Frozen):
    id: str
    change: str
    title: str
    repo: str
    tier: str
    depends_on: tuple[str, ...] = ()
    # The subset of `depends_on` that must merge before this unit starts.
    merge_before: tuple[str, ...] = ()
    estimated_lines: int = 0
    state: str = PLANNED
    issue: int | None = None
    groups: tuple[int, ...] = ()
    joined: tuple[Member, ...] = ()

    def members(self) -> tuple[Member, ...]:
        """Every change's groups this unit builds: its own first, then carried ones."""
        return (Member(change=self.change, groups=self.groups), *self.joined)

    def taking(self, taken: Sequence[Member], *, estimated_lines: int) -> Self:
        """This unit with `taken` built after its own members, and its estimate
        grown by `estimated_lines`. Work of the change the unit already ends
        on extends that member rather than starting another."""
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
            }
        )

    def carries(self, change: str) -> bool:
        """Does this unit build any of `change`'s groups, its own or carried?"""
        return any(member.change == change for member in self.members())


def branch_name(unit: Unit) -> str:
    """`spec/<change>/<n>` — deterministic, so a re-run reuses the branch.

    Nothing derived from the title or a timestamp: a renamed unit must land on
    the same branch, or the work already committed there is orphaned. The one
    place a unit's branch is spelled; the prefix is the setting the command
    policy and the poller use to recognise these branches.
    """
    return f"{active().git.branch_prefix}{unit.id}"


def local_ref(base: str) -> str:
    """The ref to build on locally for a PR base named `base`.

    A unit's own branch is local — its parent's worktree commits to it. The
    trunk is not: `main` in the code repo's checkout is the user's, and nothing
    updates it. Building on it puts a unit on a `main` from before its
    predecessor merged, so its review judges it against a group that no
    longer exists. The trunk is taken from the remote, which
    each tick fetches first; the PR's base stays the bare name GitHub knows.
    """
    return base if base.startswith(active().git.branch_prefix) else f"origin/{base}"


def plan_units(change: str, groups: list[dict], *, min_lines: int, max_lines: int) -> list[Unit]:
    """Group consecutive task groups into units.

    Absorbing continues until the estimate reaches `min_lines`, because a
    chain of small groups would otherwise become a stack of trivial PRs, each
    costing an issue, a tier 2 run, a restack and a merge. It stops early at a
    fan-out point — a group other units are waiting on — since finishing that
    sooner lets them start. It never combines groups past `max_lines`: a group
    that would take the unit over it starts a unit of its own.

    A unit never spans repos: a branch lives in one, so its unit does too.
    """
    units: list[Unit] = []
    current: list[dict] = []
    # The unit the next chained group depends on. An independent group is
    # outside the chain: it neither takes this tail nor moves it.
    tail: str | None = None
    independent_seen = False

    def flush() -> None:
        nonlocal tail, independent_seen
        if not current:
            return
        unit_id = f"{change}/{len(units) + 1}"
        alone = bool(current[0].get("independent"))
        # A group that exercises or removes what the others built waits for
        # every earlier unit once any of them is off the chain.
        waits_for_all = current[0].get("flag") in ("acceptance", "narrow") and independent_seen
        if alone:
            depends_on: tuple[str, ...] = ()
        elif waits_for_all:
            depends_on = tuple(u.id for u in units)
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
                # A unit that needs the live stack anywhere needs it overall:
                # tier decides how it's verified, not what belongs together.
                tier="tier2" if any(g["tier"] == "tier2" for g in current) else "tier1",
                estimated_lines=sum(g["estimated_lines"] for g in current),
                groups=tuple(g["number"] for g in current),
                depends_on=depends_on,
            )
        )
        if alone:
            independent_seen = True
        else:
            tail = unit_id
        current.clear()

    for group in groups:
        independent = bool(group.get("independent"))
        # Joining is a form of ordering, so an independent group is joined
        # neither to the unit before it nor to the one after.
        if current and (independent or group["repo"] != current[0]["repo"]):
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
        for other in parent.depends_on:
            if other in index and index[other].repo == parent.repo:
                out.extend(expand(other, seen))
            else:
                out.append(other)
        return tuple(out)

    out: list[str] = []
    for dep in unit.depends_on:
        parent = index.get(dep)
        if parent is not None and parent.repo == unit.repo:
            out.extend(expand(dep, frozenset()))
        else:
            out.append(dep)
    return tuple(out)


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

    Its newest still-open dependency in the same repo, or the repo's default
    branch when they have all merged. Nothing starts from the trunk by default:
    if the work it needs is in flight, stacking on it is what keeps the two from
    duplicating or conflicting.

    A same-repo dependency that is satisfied is transparent (see
    `through_satisfied`): it has no branch of its own, so its dependent stacks
    on whatever it depended on instead — its still-open predecessor, or `main`
    once that predecessor has also merged.

    A cross-repo dependency is never a base — stacks can't span repos, so that
    edge is an ordering constraint instead, and `ready_units` makes the
    dependent wait for a merge.
    """
    index = _by_id(graph)
    candidates = [
        index[dep]
        for dep in through_satisfied(unit, graph)
        if dep in index and index[dep].repo == unit.repo and index[dep].state == IN_REVIEW
    ]
    if not candidates:
        return trunk_of(unit.repo)
    return branch_name(candidates[-1])


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
            for dep in current.depends_on
            if dep in index and index[dep].repo == current.repo and dep not in seen
        ]
        return all(
            dep.state == MERGED or (dep.state == SATISFIED and landed(dep, seen | {current.id}))
            for dep in same_repo
        )

    return landed(unit, frozenset())


def waiting_on(unit: Unit, graph: Sequence[Unit]) -> list[Unit]:
    """The dependencies that stop `unit` starting now.

    Same-repo ones must be complete — through the build/review loop, so there
    is a reviewed branch to stack on. A satisfied one is looked through
    (`through_satisfied`), as `base_of` does: it has no branch of its own, so
    what `unit` waits on is what that dependency was built on. Its predecessor
    sent back for rework, or failed, holds `unit` too; in review or merged it
    does not. Cross-repo ones must have merged: the dependent can't stack on
    them, so it waits rather than building against a moving target — as does
    a same-repo one the unit lists in `merge_before` — except a
    satisfied cross-repo dependency, which never merges itself; it is done
    once its own same-repo work has (`satisfied_landed`). The scheduler and
    the diagram both ask this, so the graph never shows a unit as startable
    that the tick would hold back.
    """
    index = _by_id(graph)
    waiting: list[Unit] = []

    def landed(parent: Unit) -> bool:
        return parent.state == MERGED or (
            parent.state == SATISFIED and satisfied_landed(parent, graph)
        )

    # A gated dependency is judged as itself, before any look-through: a
    # satisfied one is not replaced by its predecessor, since what the unit
    # wants is that dependency's work on the trunk.
    for dep in unit.depends_on:
        parent = index.get(dep)
        if dep in unit.merge_before and parent is not None and not landed(parent):
            waiting.append(parent)
    ungated = unit.model_copy(
        update={"depends_on": tuple(d for d in unit.depends_on if d not in unit.merge_before)}
    )
    for dep in through_satisfied(ungated, graph):
        parent = index.get(dep)
        if parent is None:
            continue
        if parent.repo == unit.repo:
            if parent.state not in REVIEWED:
                waiting.append(parent)
        elif not landed(parent):
            waiting.append(parent)
    return waiting


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
            if other.id != unit.id and other.state != "unplanned"
            for carried in other.members()
            if carried.change == change
            for group in carried.groups
            if group > ceiling and group not in own
        }
        if others:
            later[change] = tuple(sorted(others))
    return later


def in_progress(unit: Unit) -> bool:
    """Whether the unit has been started and not finished (docs/architecture.md).

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
    """
    if unit.state in (MERGED, CLOSED, SATISFIED, HELD):
        return False
    if unit.state in (RUNNING, IN_REVIEW, FAILED):
        return True
    return _worked_on(unit)


def _worked_on(unit: Unit) -> bool:
    """Whether a run has already done something to the unit: the graph records
    its branch when a run begins, then the pushed and approved commits."""
    return (
        getattr(unit, "pr", None) is not None
        or bool(getattr(unit, "branch", ""))
        or bool(getattr(unit, "pushed", None))
        or bool(getattr(unit, "approved", ""))
    )


def in_progress_label(unit: Unit) -> str:
    """Why an in-progress unit counts, for the report of a full queue.

    A planned or unplanned unit is in progress only because something was
    already done to it, so it is named for that, not `planned`: "reworking"
    with a pull request, "paused" with only a branch of work.
    """
    if unit.state in (PLANNED, "unplanned"):
        return "reworking" if getattr(unit, "pr", None) is not None else "paused"
    return unit.state.replace("_", " ")


def start_room(graph: Sequence[Unit], limit: int) -> int:
    """How many never-started units may begin before `limit` is reached."""
    return max(0, limit - sum(1 for unit in graph if in_progress(unit)))


def _start_rank(unit: Unit) -> int:
    """Existing work first: an open pull request, then a paused build, then new."""
    if getattr(unit, "pr", None) is not None:
        return 0
    return 1 if _worked_on(unit) else 2


def ready_units(
    graph: Sequence[Unit],
    *,
    max_concurrent: int,
    depth_cap: int,
    max_units_in_progress: int | None = None,
) -> list[Unit]:
    """The planned units that may start right now, in the order to start them.

    A unit is ready when every dependency allows it: same-repo dependencies
    may be open (it stacks on them), cross-repo ones must have merged. A
    satisfied dependency is looked through to what it was built on, so a unit
    is not ready while that predecessor is still being built, failed or held. The
    depth cap then holds back chains that have run too far ahead of review
    without touching their siblings, and the concurrency cap limits how many
    units are being built at once.

    `max_units_in_progress` bounds the units started and not finished, across
    all repos (`in_progress`). A unit that has never started begins only while
    that leaves room, and no more of them than it does; one already in
    progress (a rework, a resume, a unit finishing its review loop) always may,
    since running it is how the queue drains.

    Free slots go to units with an open pull request, then to those resuming
    a build, then to new ones, each in the order they were planned.
    """
    running = sum(1 for unit in graph if unit.state == RUNNING)
    slots = max(0, max_concurrent - running)
    if not slots:
        return []

    room = None if max_units_in_progress is None else start_room(graph, max_units_in_progress)

    ready: list[Unit] = []
    for unit in graph:
        if unit.state != PLANNED:
            continue

        if waiting_on(unit, graph):
            continue

        if depth_of(unit, graph) > depth_cap:
            continue

        ready.append(unit)

    started: list[Unit] = []
    for unit in sorted(ready, key=_start_rank):
        if len(started) == slots:
            break
        if room is not None and not in_progress(unit):
            if not room:
                continue
            room -= 1
        started.append(unit)
    return started
