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
    holds a lane place; `lane_workers` counts those of them a run holds, which are also in
    `workers`; `leased` counts the units a person holds a lease on, which take no place or
    worker by that."""

    projects: Mapping[ProjectKey, int] = {}
    workers: Mapping[ProjectKey, int] = {}
    accounts: Mapping[str | None, int] = {}
    emergency: Mapping[ProjectKey, int] = {}
    lane_workers: Mapping[ProjectKey, int] = {}
    leased: Mapping[ProjectKey, int] = {}


class Limits(Frozen):
    """What occupancy is held to: build workers of one project, the lane's extra places in one
    project, the units in progress of one project (None: not counted per project), and the
    places of each account label that has its own."""

    stacks: int
    emergency_extra: int = 0
    in_progress: int | None = None
    accounts: Mapping[str | None, int] = {}


def no_account(unit: Unit) -> str | None:
    """The account of every unit when none is configured: the default account."""
    return None


def marker_live(unit: StoredUnit, now: datetime) -> bool:
    """Whether the unit's `starting` marker has not lapsed at `now`."""
    return unit.starting is not None and unit.starting.until > now


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
    account_of: Callable[[Unit], str | None] = no_account,
) -> Occupancy:
    """The occupancy of `units`: those a run holds, which hold a worker and a place: whose branch
    is in `locks` (the branches live locks name), whose `starting` marker has not lapsed at
    `now`, or that a run the caller knows of holds (`held`: its builds in flight and the runs of
    its restack lane, which have not all written a lock yet). A unit that records a usage pause
    and no run holds a place and no worker. A unit whose id is in `leases` (the units live
    leases name) is recorded as leased, and a lease alone takes neither: a person chatting with a
    unit is not a build. Those also in `lane` count in their project's emergency lane."""
    projects: Counter[ProjectKey] = Counter()
    workers: Counter[ProjectKey] = Counter()
    accounts: Counter[str | None] = Counter()
    emergency: Counter[ProjectKey] = Counter()
    lane_workers: Counter[ProjectKey] = Counter()
    leased: Counter[ProjectKey] = Counter()
    for unit in units:
        key = project_key(unit)
        if unit.id in leases:
            leased[key] += 1
        runs = (
            (unit.branch or branch_name(unit)) in locks or unit.id in held or marker_live(unit, now)
        )
        if not (runs or usage_paused(unit)):
            continue
        projects[key] += 1
        accounts[account_of(unit)] += 1
        if unit.id in lane:
            emergency[key] += 1
        if runs:
            workers[key] += 1
            if unit.id in lane:
                lane_workers[key] += 1
    return Occupancy(
        projects=dict(projects),
        workers=dict(workers),
        accounts=dict(accounts),
        emergency=dict(emergency),
        lane_workers=dict(lane_workers),
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
    it is not taken off."""
    busy = occupancy.workers.get(project, 0) - (
        0 if new else occupancy.lane_workers.get(project, 0)
    )
    room = limits.stacks - busy
    if new:
        if limits.in_progress is not None:
            room = min(room, limits.in_progress - occupancy.projects.get(project, 0))
        if account in limits.accounts:
            room = min(room, limits.accounts[account] - occupancy.accounts.get(account, 0))
    return max(0, room)


def free_workers(occupancy: Occupancy, limits: Limits, project: ProjectKey) -> int:
    """How many of `project`'s workers hold no unit, for the report of the slots."""
    return max(0, limits.stacks - occupancy.workers.get(project, 0))


def emergency_free(occupancy: Occupancy, limits: Limits, project: ProjectKey) -> int:
    """How many more units may start in `project`'s emergency lane."""
    return max(0, limits.emergency_extra - occupancy.emergency.get(project, 0))


def capacity(limits: Limits, projects: int) -> int:
    """The workers and lane places of `projects` projects together."""
    return (limits.stacks + limits.emergency_extra) * projects
