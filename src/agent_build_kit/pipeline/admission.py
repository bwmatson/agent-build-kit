"""Admission: count, check and mark under one lock, so two admitters never pass a limit."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.emergency_lane import lane_units
from agent_build_kit.pipeline.file_lock import file_lock
from agent_build_kit.pipeline.lease import Leases
from agent_build_kit.pipeline.occupancy import Limits, Occupancy, free, marker_live, occupied
from agent_build_kit.pipeline.unit_store import Starting, StoredUnit, UnitStore
from agent_build_kit.pipeline.units import branch_name, project_key
from agent_build_kit.pipeline.workspaces import branch_held


def _occupancy(inst: Installation, units: Sequence[StoredUnit], now: datetime) -> Occupancy:
    """The occupancy the durable facts show: live branch locks, live leases, live markers and
    recorded usage pauses."""
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
    )


def admit(
    inst: Installation,
    store: UnitStore,
    candidates: Sequence[StoredUnit],
    *,
    worker: str,
    now: datetime,
    ttl: timedelta,
) -> list[StoredUnit]:
    """The leading `candidates` that fit the free slots, each marked `starting` for `worker`
    until `now + ttl` before the admission lock (`admission.lock` in the locks folder) is
    released."""
    limits = Limits(stacks=inst.max_concurrent_stacks, emergency_extra=inst.emergency_extra)
    admitted: list[str] = []
    with file_lock(inst.locks_dir / "admission.lock"):
        for candidate in candidates:
            units = store.all()
            current = store.get(candidate.id)
            if marker_live(current, now):
                continue
            if free(_occupancy(inst, units, now), limits, project_key(current)) > 0:
                store.set_starting(current.id, Starting(worker=worker, until=now + ttl))
                admitted.append(current.id)
    return [store.get(unit_id) for unit_id in admitted]
