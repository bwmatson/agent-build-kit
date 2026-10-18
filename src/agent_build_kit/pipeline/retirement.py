"""What retiring a unit would do, decided from the units alone.

Spec: a-started-unit-keeps-its-groups.

`assess` answers, before anything changes, whether a unit may be retired, what becomes of each
group it carries and which units stop waiting on it. `abk retire` and the status read it.
"""

from __future__ import annotations

from collections.abc import Sequence

from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.unit_store import StoredUnit
from agent_build_kit.pipeline.units import (
    FINISHED_STATES,
    MERGED,
    RUNNING,
    SATISFIED,
    UnitState,
    current_dependencies,
    satisfied_landed,
)


class GroupFate(Frozen):
    """One group the unit carries: `carried_by` is the other unit that builds it (empty when
    none does) and `merged` says that unit has built it (merged or satisfied) rather than
    still owning it."""

    change: str
    group: int
    carried_by: str = ""
    merged: bool = False


class Dependent(Frozen):
    """A unit that depends on the one retired, and has not finished."""

    id: str
    state: str


class Assessment(Frozen):
    """`refusal` is empty when the unit may be retired, else why not; `reason_required` is true
    when any group is carried by no unit."""

    unit: str
    refusal: str = ""
    groups: tuple[GroupFate, ...] = ()
    dependents: tuple[Dependent, ...] = ()
    reason_required: bool = False


def _fate(unit: StoredUnit, change: str, group: int, others: Sequence[StoredUnit]) -> GroupFate:
    """What becomes of one group of `unit`: built by a merged or satisfied unit, still owned by
    another, or carried by none."""
    carrying = [
        other
        for other in others
        if other.id != unit.id
        and any(m.change == change and group in m.groups for m in other.members())
    ]
    for other in carrying:
        if other.state == MERGED or (other.state == SATISFIED and satisfied_landed(other, others)):
            return GroupFate(change=change, group=group, carried_by=other.id, merged=True)
    for other in carrying:
        if other.owns_groups:
            return GroupFate(change=change, group=group, carried_by=other.id)
    return GroupFate(change=change, group=group)


def _refusal(unit: StoredUnit, units: Sequence[StoredUnit]) -> str:
    if unit.state in FINISHED_STATES:
        return f"{unit.id} is finished ({unit.state})"
    if unit.state == RUNNING:
        return f"{unit.id} is running; stop it first"
    for other in units:
        if (
            unit.id in current_dependencies(other, units)
            and other.repo == unit.repo
            and other.has_work
            and other.state not in FINISHED_STATES
        ):
            return f"{other.id} has started and is stacked on {unit.id}"
    return ""


def assess(unit_id: str, units: Sequence[StoredUnit]) -> Assessment:
    """Whether `unit_id` may be retired and what retiring it leaves behind."""
    unit = next(u for u in units if u.id == unit_id)
    groups = tuple(
        _fate(unit, member.change, group, units)
        for member in unit.members()
        for group in member.groups
    )
    dependents = tuple(
        Dependent(id=other.id, state=str(other.state))
        for other in units
        if unit_id in current_dependencies(other, units)
        and other.state not in (*FINISHED_STATES, UnitState.UNPLANNED)
    )
    return Assessment(
        unit=unit_id,
        refusal=_refusal(unit, units),
        groups=groups,
        dependents=dependents,
        reason_required=any(not fate.carried_by for fate in groups),
    )
