"""Which `running` units no run holds.

Spec: retire-takes-an-idle-running-unit.

The scheduler (`slot_occupancy`) and `abk retire` both ask this, so they agree on what idle
means: stored `running`, not handed to a worker in this pass, the branch's lock not held by
a live process, and no unexpired `starting` marker: a worker admission sent it to is on its way to
the lock.
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Iterable
from datetime import datetime

from agent_build_kit.pipeline.occupancy import marker_live
from agent_build_kit.pipeline.unit_store import StoredUnit
from agent_build_kit.pipeline.units import RUNNING, branch_name


def idle_units(
    units: Iterable[StoredUnit],
    in_flight: Collection[str],
    branch_is_held: Callable[[str], bool],
    *,
    now: datetime,
) -> set[str]:
    """Running units no run holds: not in flight, their branch's lock free and no live marker."""
    return {
        unit.id
        for unit in units
        if unit.state == RUNNING
        and unit.id not in in_flight
        and not marker_live(unit, now)
        and not branch_is_held(unit.branch or branch_name(unit))
    }
