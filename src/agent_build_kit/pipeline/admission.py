"""Admission under a lock: count occupancy, check limits and mark the units admitted."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import timedelta

from agent_build_kit import claude_account
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline import emergency_lane, spans
from agent_build_kit.pipeline.file_lock import file_lock
from agent_build_kit.pipeline.lease import Leases, lease_dir
from agent_build_kit.pipeline.occupancy import Limits, free, occupied
from agent_build_kit.pipeline.unit_store import Starting, StoredUnit, UnitStore
from agent_build_kit.pipeline.units import Unit, branch_name, project_key
from agent_build_kit.pipeline.workspaces import branch_held

STARTING_TTL = timedelta(seconds=120)


def _account_of(inst: Installation, unit: Unit) -> str:
    """The account a unit's slot is counted under: its label when the installation counts
    slots per account, else the one account."""
    if not claude_account.slots_per_account(inst.config):
        return ""
    return claude_account.for_repo(inst.config, unit.repo).label or ""


def _occupancy(inst: Installation, units: Sequence[StoredUnit]):
    locks_dir = inst.state_dir / "locks"
    leases = Leases(lease_dir(inst.state_dir))
    return occupied(
        units,
        locks={
            unit.branch or branch_name(unit)
            for unit in units
            if branch_held(unit.branch or branch_name(unit), root=locks_dir)
        },
        leases={unit.id for unit in units if leases.holder(unit.id) is not None},
        now=spans.clock.now(),
        lane=emergency_lane.lane_units(inst.state_dir),
        account_of=lambda unit: _account_of(inst, unit),
    )


def admit(
    inst: Installation,
    store: UnitStore,
    candidates: Sequence[Unit],
    *,
    worker: str,
    ttl: timedelta = STARTING_TTL,
) -> list[Unit]:
    """The leading `candidates` that fit the free slots, each marked `starting` for `worker`
    until `ttl` from now, all under `runs/locks/admission.lock`."""
    limits = Limits(
        stacks=inst.max_concurrent_stacks,
        emergency=inst.emergency_extra,
        in_progress=inst.max_units_in_progress,
    )
    admitted: list[Unit] = []
    with file_lock(inst.state_dir / "locks" / "admission.lock"):
        for unit in candidates:
            # Counted afresh each time: a marker written just now holds its slot.
            found = _occupancy(inst, store.all())
            room = free(found, limits, project=project_key(unit), account=_account_of(inst, unit))
            if room <= 0:
                continue
            until = spans.clock.now() + ttl
            store.set_starting(unit.id, Starting(worker=worker, until=until))
            admitted.append(unit)
    return admitted
