"""Which `running` units no run holds.

Spec: retire-takes-an-idle-running-unit.

The scheduler (`slot_occupancy`) and `abk retire` both ask this, so they agree on what idle
means: stored `running`, not handed to a worker in this pass, and the branch's lock not held by
a live process.
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Iterable

from agent_build_kit.pipeline.unit_store import StoredUnit
from agent_build_kit.pipeline.units import RUNNING, branch_name


def idle_units(
    units: Iterable[StoredUnit],
    in_flight: Collection[str],
    branch_is_held: Callable[[str], bool],
) -> set[str]:
    """Running units no run holds: not in flight, and their branch's lock free."""
    return {
        unit.id
        for unit in units
        if unit.state == RUNNING
        and unit.id not in in_flight
        and not branch_is_held(unit.branch or branch_name(unit))
    }
