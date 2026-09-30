"""Units of work: where the boundaries fall, and which may run now.

A change's `tasks.md` is a list of task groups. A unit is one PR's worth of
them, in one repo (docs/architecture.md). This module holds the
rules that turn one into the other, and the scheduling questions that follow:
what a unit stacks on, how deep its chain is, and which units are ready.

Everything here is pure. The planner that produces the estimates, and the
parts that talk to git and GitHub, live elsewhere — so these rules can be
argued with directly, in tests, rather than through a subprocess.
"""

from __future__ import annotations

from collections.abc import Sequence

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

# A reviewer has asked the pipeline to keep its hands off this unit. Not a
# lifecycle state like the ones above: those describe how far a unit has got,
# and this describes who is driving it.
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


class Unit(Frozen):
    id: str
    change: str
    title: str
    repo: str
    tier: str
    depends_on: tuple[str, ...] = ()
    estimated_lines: int = 0
    state: str = PLANNED
    issue: int | None = None
    groups: tuple[int, ...] = ()


def branch_name(unit: Unit) -> str:
    """`spec/<change>/<n>` — deterministic, so a re-run reuses the branch.

    Nothing derived from the title or a timestamp: a renamed unit must land on
    the same branch, or the work already committed there is orphaned. The one
    place a unit's branch is spelled; the prefix is the setting the command
    policy and the poller use to recognise these branches.
    """
    return f"{active().github.branch_prefix}{unit.id}"


def local_ref(base: str) -> str:
    """The ref to build on locally for a PR base named `base`.

    A unit's own branch is local — its parent's worktree commits to it. The
    trunk is not: `main` in the code repo's checkout is the user's, and nothing
    updates it. Building on it puts a unit on a `main` from before its
    predecessor merged, so its review judges it against a group that no
    longer exists. The trunk is taken from the remote, which
    each tick fetches first; the PR's base stays the bare name GitHub knows.
    """
    return base if base.startswith(active().github.branch_prefix) else f"origin/{base}"


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

    def flush() -> None:
        if not current:
            return
        number = len(units) + 1
        units.append(
            Unit(
                id=f"{change}/{number}",
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
                depends_on=(units[-1].id,) if units else (),
            )
        )
        current.clear()

    for group in groups:
        if current and group["repo"] != current[0]["repo"]:
            flush()

        size = sum(g["estimated_lines"] for g in current) + group["estimated_lines"]
        if current and size > max_lines:
            flush()
            size = group["estimated_lines"]

        current.append(group)

        if group.get("fans_out") or size >= min_lines:
            flush()

    flush()
    return units


def _by_id(graph: Sequence[Unit]) -> dict[str, Unit]:
    return {unit.id: unit for unit in graph}


def base_of(unit: Unit, graph: Sequence[Unit]) -> str:
    """The branch this unit builds on.

    Its newest still-open dependency in the same repo, or `main` when they
    have all merged. Nothing starts from `main` by default: if the work it
    needs is in flight, stacking on it is what keeps the two from duplicating
    or conflicting.

    A cross-repo dependency is never a base — stacks can't span repos, so that
    edge is an ordering constraint instead, and `ready_units` makes the
    dependent wait for a merge.
    """
    index = _by_id(graph)
    candidates = [
        index[dep]
        for dep in unit.depends_on
        if dep in index and index[dep].repo == unit.repo and index[dep].state == IN_REVIEW
    ]
    if not candidates:
        return "main"
    return branch_name(candidates[-1])


def depth_of(unit: Unit, graph: Sequence[Unit]) -> int:
    """Length of the longest chain of open ancestors, counting this unit.

    Merged ancestors drop out, which is what makes merging the bottom PR free
    a layer for everything above it. Siblings on a shared base share a depth
    rather than adding to it: a stack is a tree, not a line.
    """
    index = _by_id(graph)

    def walk(current: Unit, seen: frozenset[str]) -> int:
        open_parents = [
            index[dep]
            for dep in current.depends_on
            if dep in index
            and dep not in seen
            and index[dep].repo == current.repo
            and index[dep].state == IN_REVIEW
        ]
        if not open_parents:
            return 1
        return 1 + max(walk(parent, seen | {current.id}) for parent in open_parents)

    return walk(unit, frozenset())


def waiting_on(unit: Unit, graph: Sequence[Unit]) -> list[Unit]:
    """The dependencies that stop `unit` starting now.

    Same-repo ones must be complete — through the build/review loop, so there
    is a reviewed branch to stack on. Cross-repo ones must have merged: the
    dependent can't stack on them, so it waits rather than building against a
    moving target. The scheduler and the diagram both ask this, so the graph
    never shows a unit as startable that the tick would hold back.
    """
    index = _by_id(graph)
    waiting: list[Unit] = []
    for dep in unit.depends_on:
        parent = index.get(dep)
        if parent is None:
            continue
        done = REVIEWED if parent.repo == unit.repo else (MERGED,)
        if parent.state not in done:
            waiting.append(parent)
    return waiting


def later_groups(unit: Unit, graph: Sequence[Unit]) -> tuple[int, ...]:
    """Task groups of this change that belong to units after this one.

    Group numbers only increase through `tasks.md`, so anything above this
    unit's own highest group is later work — whichever unit the plan gave it
    to, and whether or not that unit has run yet.
    """
    ceiling = max(unit.groups, default=0)
    others = {
        group
        for other in graph
        if other.id != unit.id and other.change == unit.change
        for group in other.groups
        if group > ceiling
    }
    return tuple(sorted(others))


def ready_units(graph: Sequence[Unit], *, max_concurrent: int, depth_cap: int) -> list[Unit]:
    """The planned units that may start right now.

    A unit is ready when every dependency allows it: same-repo dependencies
    may be open (it stacks on them), cross-repo ones must have merged. The
    depth cap then holds back chains that have run too far ahead of review
    without touching their siblings, and the concurrency cap limits how many
    units are being built at once — not how many PRs await review, which is
    deliberately unbounded.
    """
    running = sum(1 for unit in graph if unit.state == RUNNING)
    slots = max(0, max_concurrent - running)
    if not slots:
        return []

    ready: list[Unit] = []
    for unit in graph:
        if unit.state != PLANNED:
            continue

        if waiting_on(unit, graph):
            continue

        if depth_of(unit, graph) > depth_cap:
            continue

        ready.append(unit)
        if len(ready) >= slots:
            break

    return ready
