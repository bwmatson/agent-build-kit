"""Slot occupancy: one pure function over the durable facts, and the free slots against limits."""

from __future__ import annotations

from collections.abc import Callable, Collection, Mapping, Sequence
from datetime import datetime

from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.unit_store import StoredUnit
from agent_build_kit.pipeline.units import ProjectKey


class Occupancy(Frozen):
    """The slots in use: per project, per account, and the emergency lane's."""

    projects: Mapping[ProjectKey, int] = {}
    accounts: Mapping[str, int] = {}
    emergency: int = 0


class Limits(Frozen):
    """What occupancy is held to; an account without its own limit gets `in_progress`."""

    stacks: int
    emergency: int
    in_progress: int
    accounts: Mapping[str, int] = {}


def occupied(
    units: Sequence[StoredUnit],
    *,
    locks: Collection[str],
    leases: Collection[str],
    now: datetime,
    lane: Collection[str] = (),
    account_of: Callable[[StoredUnit], str] | None = None,
) -> Occupancy:
    """The slots units hold: a unit holds one when its branch is in `locks` (live branch locks),
    its id is in `leases`, or its `starting` marker has not expired at `now`; each unit once. A
    unit in `lane` counts for the emergency lane and for no project."""
    raise NotImplementedError


def free(occupancy: Occupancy, limits: Limits, *, project: ProjectKey, account: str = "") -> int:
    """The units a project and account can still start: the smaller of its free stacks and its
    account's free slots, never below zero."""
    raise NotImplementedError


def emergency_free(occupancy: Occupancy, limits: Limits) -> int:
    """The emergency lane's free places, never below zero."""
    raise NotImplementedError
