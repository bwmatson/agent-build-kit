"""Slot occupancy from durable facts, as a pure function of plain data.

A unit occupies a place while a live branch lock, an unexpired `starting` marker, a run the caller
knows of or a recorded usage pause names it. Of those, the ones a run holds (everything but a
pause alone) also hold a worker. A live lease is recorded and takes neither. Nothing here reads a
file or the clock.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Collection, Mapping, Sequence
from datetime import datetime

from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.unit_store import StoredUnit
from agent_build_kit.pipeline.units import RUNNING, ProjectKey, Unit, branch_name, project_key


class Occupancy(Frozen):
    """Units occupying places, each counted once. `projects` and `accounts` count the units in
    progress here (a paused unit among them) in each project and under each account label (None
    for the default account); `workers` counts those of them a run holds in each project (a unit
    named only by its usage pause does not); `emergency` counts the lane's units, each of which
    holds a lane place, in each project and `account_emergency` under each account label;
    `lane_workers` counts those of them a run holds, which are also in
    `workers`; `leased` counts the units a person holds a lease on, which take no place or
    worker by that."""

    projects: Mapping[ProjectKey, int] = {}
    workers: Mapping[ProjectKey, int] = {}
    accounts: Mapping[str | None, int] = {}
    emergency: Mapping[ProjectKey, int] = {}
    account_emergency: Mapping[str | None, int] = {}
    lane_workers: Mapping[ProjectKey, int] = {}
    account_workers: Mapping[str | None, int] = {}
    leased: Mapping[ProjectKey, int] = {}


class Limits(Frozen):
    """What occupancy is held to: build workers of one project, the lane's extra places in one
    project, the units in progress of one project (None: not counted per project), and the
    places of each account label that has its own, and the builds at once of each account label
    that caps them across its projects, and the lane places of each account label that caps them
    across its projects."""

    stacks: int
    emergency_extra: int = 0
    in_progress: int | None = None
    accounts: Mapping[str | None, int] = {}
    account_stacks: Mapping[str | None, int] = {}
    account_extras: Mapping[str | None, int] = {}


def no_account(unit: Unit) -> str | None:
    """The account of every unit when none is configured: the default account."""
    return None


RESOLVE_CLAIM = "resolve-"


def marker_live(unit: StoredUnit, now: datetime) -> bool:
    """Whether the unit's `starting` marker has not lapsed at `now`."""
    return unit.starting is not None and unit.starting.until > now


def resolve_claimed(unit: StoredUnit, now: datetime) -> bool:
    """Whether the unit's live `starting` marker is the claim of a resolve worker (its `worker`
    starts with `RESOLVE_CLAIM`): a place in the resolution lane, not a build worker."""
    return (
        marker_live(unit, now)
        and unit.starting is not None
        and (unit.starting.worker.startswith(RESOLVE_CLAIM))
    )


def usage_paused(unit: StoredUnit) -> bool:
    """Whether the gate left the unit paused for usage: running, with a pause recorded. A pause
    is recorded until the gate allows, so one whose time has passed and is waiting for a worker
    still holds its place; `reclaim_stranded` ends it when its thread is gone. With no run on it,
    it holds its place and no worker."""
    return unit.state == RUNNING and unit.paused_until is not None


def occupied(
    units: Sequence[StoredUnit],
    *,
    locks: Collection[str],
    leases: Collection[str],
    now: datetime,
    lane: Collection[str] = (),
    held: Collection[str] = (),
    lane_held: Collection[str] = (),
    account_of: Callable[[Unit], str | None] = no_account,
) -> Occupancy:
    """The occupancy of `units`: those a run holds, which hold a worker and a place: whose branch
    is in `locks` (the branches live locks name), whose `starting` marker has not lapsed at
    `now`, or that a run the caller knows of holds (`held`: its builds in flight and the runs of
    its restack lane, which have not all written a lock yet). A comment rework with its branch
    locked that no record of the resolution lane names (`lane_held`) is a build worker's and holds
    a worker as a build does. A unit that records a usage pause
    and no run holds a place and no worker. A unit whose id is in `leases` (the units live
    leases name) is recorded as leased, and a lease alone takes neither: a person chatting with a
    unit is not a build. Those also in `lane` count in their project's emergency lane."""
    projects: Counter[ProjectKey] = Counter()
    workers: Counter[ProjectKey] = Counter()
    accounts: Counter[str | None] = Counter()
    emergency: Counter[ProjectKey] = Counter()
    account_emergency: Counter[str | None] = Counter()
    lane_workers: Counter[ProjectKey] = Counter()
    account_workers: Counter[str | None] = Counter()
    leased: Counter[ProjectKey] = Counter()
    for unit in units:
        key = project_key(unit)
        if unit.id in leases:
            leased[key] += 1
        # A resolve worker's claim holds a place in the lane and no build worker.
        claimed = resolve_claimed(unit, now)
        runs = (
            (unit.branch or branch_name(unit)) in locks
            or unit.id in held
            or (marker_live(unit, now) and not claimed)
        )
        # A comment rework in the resolution lane holds its place and its branch lock, and no
        # build worker (`ready_units` shows it running with no worker); one a build worker runs
        # (the branch locked, no record of the lane naming it) holds a worker as a build does.
        locked = (unit.branch or branch_name(unit)) in locks
        comment_run = unit.in_a_comment_run and not unit.in_a_worker(
            locked=locked, lane_held=lane_held
        )
        if not (runs or comment_run or claimed or usage_paused(unit)):
            continue
        projects[key] += 1
        accounts[account_of(unit)] += 1
        if unit.id in lane:
            emergency[key] += 1
            account_emergency[account_of(unit)] += 1
        if runs and not comment_run:
            workers[key] += 1
            account_workers[account_of(unit)] += 1
            if unit.id in lane:
                lane_workers[key] += 1
    return Occupancy(
        projects=dict(projects),
        workers=dict(workers),
        accounts=dict(accounts),
        emergency=dict(emergency),
        account_emergency=dict(account_emergency),
        lane_workers=dict(lane_workers),
        account_workers=dict(account_workers),
        leased=dict(leased),
    )


def free(
    occupancy: Occupancy,
    limits: Limits,
    project: ProjectKey,
    account: str | None = None,
    *,
    new: bool = True,
) -> int:
    """How many more units of `project` may start: its free workers and, for a unit `new` to
    progress, no more than the units in progress the project allows and the account's own limit
    when `limits` names one. The lane's units hold a worker for a unit `new` to progress, so
    ordinary starts wait; a unit already in progress is held to the workers without them
    (`ready_units`); a lane unit named only by its pause holds a lane place and no worker, so
    it is not taken off. An account that caps its builds holds every unit of its projects to
    that cap together: a unit already in progress is held to it as it is to the project's workers,
    and only the units in progress limit is bypassed."""
    busy = occupancy.workers.get(project, 0) - (
        0 if new else occupancy.lane_workers.get(project, 0)
    )
    room = limits.stacks - busy
    if (capped := account_room(occupancy, limits, account)) is not None:
        room = min(room, capped)
    if new:
        if limits.in_progress is not None:
            room = min(room, limits.in_progress - occupancy.projects.get(project, 0))
        if account in limits.accounts:
            room = min(room, limits.accounts[account] - occupancy.accounts.get(account, 0))
    return max(0, room)


def account_room(occupancy: Occupancy, limits: Limits, account: str | None) -> int | None:
    """How many more builds `account` allows across its projects: its cap less the units a run
    holds, or None for an account that sets no cap on them (the default account among them)."""
    if account not in limits.account_stacks:
        return None
    return limits.account_stacks[account] - occupancy.account_workers.get(account, 0)


def free_workers(
    occupancy: Occupancy,
    limits: Limits,
    projects: Collection[ProjectKey],
    account_of: Callable[[ProjectKey], str | None] = lambda project: None,
) -> int:
    """How many workers hold no unit across `projects`, for the report of the slots: each
    project's free workers, and for the projects of an account that caps its builds no more than
    the account has room for (the lesser of the projects' room and the account's)."""
    by_account: dict[str | None, int] = {}
    for project in projects:
        room = max(0, limits.stacks - occupancy.workers.get(project, 0))
        label = account_of(project)
        by_account[label] = by_account.get(label, 0) + room
    return sum(
        min(room, max(0, limits.account_stacks[label] - occupancy.account_workers.get(label, 0)))
        if label in limits.account_stacks
        else room
        for label, room in by_account.items()
    )


def emergency_free(
    occupancy: Occupancy, limits: Limits, project: ProjectKey, account: str | None
) -> int:
    """How many more units may start in `project`'s emergency lane: its own places and, when
    `limits` names an extra for `account`, no more than the account has left across its
    projects."""
    room = limits.emergency_extra - occupancy.emergency.get(project, 0)
    if account in limits.account_extras:
        room = min(
            room, limits.account_extras[account] - occupancy.account_emergency.get(account, 0)
        )
    return max(0, room)


def capacity(limits: Limits, projects: int) -> int:
    """The workers and lane places of `projects` projects together."""
    return (limits.stacks + limits.emergency_extra) * projects
