"""What retiring a unit would do, decided from the units alone.

Spec: a-started-unit-keeps-its-groups.

`assess` answers, before anything changes, whether a unit may be retired, what becomes of each
group it carries and which units stop waiting on it. `abk retire` and the status read it.
"""

from __future__ import annotations

from collections.abc import Sequence

from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.unit_store import StoredUnit


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


def assess(unit_id: str, units: Sequence[StoredUnit]) -> Assessment:
    raise NotImplementedError
