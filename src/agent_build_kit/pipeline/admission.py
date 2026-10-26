"""Admission under a lock: count occupancy, check limits and mark the units admitted."""

from __future__ import annotations

from collections.abc import Collection, Sequence
from datetime import timedelta

from agent_build_kit import claude_account
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline import emergency_lane, spans
from agent_build_kit.pipeline.file_lock import file_lock
from agent_build_kit.pipeline.lease import Leases, lease_dir
from agent_build_kit.pipeline.occupancy import (
    Limits,
    Occupancy,
    free,
    occupied,
    slot_limit,
    slot_of,
)
from agent_build_kit.pipeline.unit_store import Starting, StoredUnit, UnitStore
from agent_build_kit.pipeline.units import Unit, branch_name, project_key
from agent_build_kit.pipeline.workspaces import branch_held

STARTING_TTL = timedelta(seconds=120)


def _account_of(inst: Installation, unit: Unit) -> str:
    """The account a unit's slot is counted under, by the label `slot_of` counts it under; the
    one account when slots are not counted per account."""
    if not claude_account.slots_per_account(inst.config):
        return ""
    label = slot_of(inst)(unit)
    return label if isinstance(label, str) else ""


def _limits(inst: Installation, units: Sequence[Unit], *, lane: bool) -> Limits:
    """The limits a candidate is held to. The emergency lane's units run past the stacks, so
    its candidate is held to the stacks and the lane together. Slots are counted per account only
    when the installation says so, each account by its own limit."""
    per_account = claude_account.slots_per_account(inst.config)
    limit_of = slot_limit(inst)
    labels = {_account_of(inst, unit) for unit in units} if per_account else set()
    return Limits(
        stacks=inst.max_concurrent_stacks + (inst.emergency_extra if lane else 0),
        emergency=inst.emergency_extra,
        in_progress=inst.max_units_in_progress if per_account else None,
        accounts={label: limit_of(label or None) for label in labels},
    )


def _occupancy(
    inst: Installation, units: Sequence[StoredUnit], *, lane: Collection[str]
) -> Occupancy:
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
        lane=lane,
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
    in_lane = emergency_lane.lane_units(inst.state_dir)
    admitted: list[Unit] = []
    with file_lock(inst.state_dir / "locks" / "admission.lock"):
        for unit in candidates:
            # Counted afresh each time: a marker written just now holds its slot.
            units = store.all()
            lane = unit.id in in_lane
            # A lane unit takes a stack of its own project and the lane's place the same: the
            # lane's candidate counts the lane's units in with the project's.
            found = _occupancy(inst, units, lane=() if lane else in_lane)
            limits = _limits(inst, units, lane=lane)
            room = free(found, limits, project=project_key(unit), account=_account_of(inst, unit))
            if room <= 0:
                continue
            until = spans.clock.now() + ttl
            store.set_starting(unit.id, Starting(worker=worker, until=until))
            admitted.append(unit)
    return admitted
