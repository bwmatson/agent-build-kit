"""Admission: count, check and mark under one lock, so two admitters never pass a limit."""

from __future__ import annotations

from collections.abc import Callable, Collection, Sequence
from datetime import datetime, timedelta

from agent_build_kit import claude_account
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.emergency_lane import lane_units
from agent_build_kit.pipeline.file_lock import file_lock
from agent_build_kit.pipeline.lease import Leases
from agent_build_kit.pipeline.occupancy import (
    Limits,
    Occupancy,
    emergency_free,
    free,
    marker_live,
    no_account,
    occupied,
)
from agent_build_kit.pipeline.slots import account_labels
from agent_build_kit.pipeline.unit_store import Starting, StoredUnit, UnitStore
from agent_build_kit.pipeline.units import Unit, branch_name, in_progress, project_key
from agent_build_kit.pipeline.workspaces import branch_held

# The admission lock's file in the locks folder. It is not a `*.lock` file: those are branch locks,
# which are removed when released, and this one stays, as the claim lock does.
ADMISSION_LOCK = ".admission"

# How long a unit admitted to a worker holds its place before the worker takes the branch's lock.
STARTING_TTL = timedelta(minutes=10)


def limits_of(inst: Installation) -> Limits:
    """The limits the installation sets: workers and lane places of a project, and the units in
    progress of a project or, when they are counted per account, of each account."""
    accounts = account_labels(inst)
    return Limits(
        stacks=inst.max_concurrent_stacks,
        emergency_extra=inst.emergency_extra,
        in_progress=None if accounts else inst.max_units_in_progress,
        accounts=accounts,
    )


def account_of(inst: Installation) -> Callable[[Unit], str | None]:
    """The account label a unit counts under: its repo's, when units in progress are counted per
    account, else the default account."""
    if not account_labels(inst):
        return no_account
    return lambda unit: claude_account.for_repo(inst.config, unit.repo).label


def current_occupancy(
    inst: Installation, units: Sequence[StoredUnit], now: datetime, *, held: Collection[str] = ()
) -> Occupancy:
    """The occupancy the durable facts show: live branch locks, live markers and recorded usage
    pauses, and the units of `held` (the runs the caller knows are going); live leases are
    recorded and take no place."""
    leases = Leases(inst.leases_dir)
    return occupied(
        units,
        locks={
            branch
            for unit in units
            if branch_held(branch := unit.branch or branch_name(unit), root=inst.locks_dir)
        },
        leases={unit.id for unit in units if leases.holder(unit.id) is not None},
        now=now,
        lane=lane_units(inst.state_dir),
        held=held,
        account_of=account_of(inst),
    )


def admit(
    inst: Installation,
    store: UnitStore,
    candidates: Sequence[Unit],
    *,
    worker: str,
    now: datetime,
    ttl: timedelta,
) -> list[StoredUnit]:
    """The leading `candidates` that fit the free places, each marked `starting` for `worker`
    until `now + ttl` before the admission lock (`ADMISSION_LOCK` in the locks folder) is
    released. A candidate fits when its project has a free worker and, if it has never started,
    room in the units in progress of its project or account, its own place not counted against
    it. Failing that, a candidate the round entered in the emergency lane (by the `ready_units`
    rule) fits while the lane has a place, whatever the workers and the units in progress."""
    limits = limits_of(inst)
    account = account_of(inst)
    admitted: list[str] = []
    with file_lock(inst.locks_dir / ADMISSION_LOCK):
        for candidate in candidates:
            units = store.all()
            current = store.get(candidate.id)
            if marker_live(current, now):
                continue
            # The candidate's own place (a pause it resumes from, its lane entry) is not held
            # against it: it is the unit being placed.
            found = current_occupancy(inst, [u for u in units if u.id != current.id], now)
            key = project_key(current)
            new = not in_progress(current, units)
            fits = free(found, limits, key, account(current), new=new) > 0 or (
                current.id in lane_units(inst.state_dir) and emergency_free(found, limits, key) > 0
            )
            if fits:
                store.set_starting(current.id, Starting(worker=worker, until=now + ttl))
                admitted.append(current.id)
    return [store.get(unit_id) for unit_id in admitted]
