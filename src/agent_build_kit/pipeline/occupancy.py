"""Slot occupancy from durable facts, as a pure function of plain data.

A unit occupies a slot while a live branch lock, a live lease, an unexpired `starting` marker or a
recorded usage pause names it. Nothing here reads a file or the clock.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Collection, Mapping, Sequence
from datetime import datetime

from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.unit_store import StoredUnit
from agent_build_kit.pipeline.units import RUNNING, ProjectKey, Unit, branch_name, project_key


class Occupancy(Frozen):
    """Units occupying slots, each counted once: in each project, under each account label
    (None for the default account), and in each project's emergency lane."""

    projects: Mapping[ProjectKey, int] = {}
    accounts: Mapping[str | None, int] = {}
    emergency: Mapping[ProjectKey, int] = {}


class Limits(Frozen):
    """What occupancy is held to: build workers of one project, the lane's extra places in one
    project, and the places of each account label that has its own."""

    stacks: int
    emergency_extra: int = 0
    accounts: Mapping[str | None, int] = {}


def no_account(unit: Unit) -> str | None:
    """The account of every unit when none is configured: the default account."""
    return None


def marker_live(unit: StoredUnit, now: datetime) -> bool:
    """Whether the unit's `starting` marker has not lapsed at `now`."""
    return unit.starting is not None and unit.starting.until > now


def paused(unit: StoredUnit) -> bool:
    """Whether the unit records a usage pause: running, with the time it waits until set. It
    holds its place with no run and no worker until the gate lets it on."""
    return unit.state == RUNNING and unit.paused_until is not None


def occupied(
    units: Sequence[StoredUnit],
    *,
    locks: Collection[str],
    leases: Collection[str],
    now: datetime,
    lane: Collection[str] = (),
    account_of: Callable[[Unit], str | None] = no_account,
) -> Occupancy:
    """The occupancy of `units`: those whose branch is in `locks` (the branches live locks name),
    whose id is in `leases` (the units live leases name), whose `starting` marker has not lapsed
    at `now`, or that record a usage pause. Those also in `lane` count in their project's
    emergency lane."""
    projects: Counter[ProjectKey] = Counter()
    accounts: Counter[str | None] = Counter()
    emergency: Counter[ProjectKey] = Counter()
    for unit in units:
        if not (
            (unit.branch or branch_name(unit)) in locks
            or unit.id in leases
            or marker_live(unit, now)
            or paused(unit)
        ):
            continue
        key = project_key(unit)
        projects[key] += 1
        accounts[account_of(unit)] += 1
        if unit.id in lane:
            emergency[key] += 1
    return Occupancy(projects=dict(projects), accounts=dict(accounts), emergency=dict(emergency))


def free(
    occupancy: Occupancy, limits: Limits, project: ProjectKey, account: str | None = None
) -> int:
    """How many more units of `project` may start: its free workers, the lane's units taking
    none, and no more than the account's own limit leaves when `limits` names one for `account`."""
    used = occupancy.projects.get(project, 0) - occupancy.emergency.get(project, 0)
    room = limits.stacks - used
    if account in limits.accounts:
        room = min(room, limits.accounts[account] - occupancy.accounts.get(account, 0))
    return max(0, room)


def emergency_free(occupancy: Occupancy, limits: Limits, project: ProjectKey) -> int:
    """How many more units may start in `project`'s emergency lane."""
    return max(0, limits.emergency_extra - occupancy.emergency.get(project, 0))
