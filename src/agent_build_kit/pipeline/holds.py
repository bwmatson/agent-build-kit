"""The hold helpers the worker and the orchestrator share.

They live here, below both, so the graph and the resolution lane need not import the events
module (the dispatcher's) to read or make a hold. `pipeline.events` imports them from here.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from contextlib import AbstractContextManager
from pathlib import Path

from agent_build_kit.pipeline.shell import git
from agent_build_kit.pipeline.unit_store import Cause, HeldBy, StoredUnit, UnitStore
from agent_build_kit.pipeline.units import (
    HELD,
    IN_REVIEW,
    PLANNED,
    RUNNING,
    base_of,
    local_ref,
)

# Holds a unit's branch for the length of a handler, or raises `BranchBusy`
# because a build holds it.
Claim = Callable[[StoredUnit], AbstractContextManager[object]]

# What the label handler writes as a hold's note when the reviewer's hold has
# no reason of its own. Prose for people: nothing reads it.
HELD_BY_A_REVIEWER = "held by a reviewer"

OWED_STATES = (PLANNED, RUNNING, IN_REVIEW)
OWED_CAUSES = (Cause.BASE_CHANGED, Cause.RESTACK_DEFERRED)
# The causes of a unit owed a moved-base run: a restack is owed for the first two only.
MOVED_BASE_CAUSES = (*OWED_CAUSES, Cause.RESTACK_CONFLICT)


def held_for_depth(unit: StoredUnit) -> bool:
    """Held for the stack depth cap, which a later merge may free: by the holder
    the record keeps. A record from before it was kept is not read from its note."""
    return unit.state == HELD and unit.held_by == HeldBy.DEPTH


def held_for_its_own_reason(unit: StoredUnit) -> bool:
    """Held for a reason the hold label did not make and its removal must not undo:
    the review loop, the toolchain, a cause not recorded. A depth hold is not one,
    since a merge frees it, so the label takes it over; and a unit the label
    already holds is not held for another reason."""
    return unit.state == HELD and not unit.held_by_the_label and not held_for_depth(unit)


def held_cause(unit: StoredUnit) -> str:
    return unit.held_by or "an unrecorded cause"


def takeover_note(unit: StoredUnit, reason: str = "") -> str:
    """The note the label's hold on `unit` is recorded with. A depth hold keeps its
    own, for a person reading it; the branch it is still on is the `held_base` field."""
    if held_for_depth(unit):
        return unit.note
    return reason or HELD_BY_A_REVIEWER


def restore_depth_hold(store: UnitStore, unit: StoredUnit) -> bool:
    """Give a unit the label took a depth hold from back to that hold, as the
    `held_base` it kept says. False when the label's hold was not over one."""
    if not unit.held_base:
        return False
    store.set_state(
        unit.id,
        HELD,
        note=unit.note,
        held_by=HeldBy.DEPTH,
        cause=Cause.DEPTH,
        held_base=unit.held_base,
    )
    return True


def in_a_lane_run(unit: StoredUnit) -> bool:
    """Whether a resolve worker is making the unit's whole run, so it is that run's to resume."""
    return unit.state == RUNNING and unit.moved_base_run


def read_base_tip(
    checkouts: Mapping[str, Path], unit: StoredUnit, units: Sequence[StoredUnit]
) -> str:
    """The commit of the unit's own base, the trunk's remote ref for a unit built on it and
    its parent's branch for a stacked one, in the unit's repo checkout; raises when it cannot
    be read. The one reading of a tip, so the conflict handler's attempts and the restack
    lane's are counted at the same commit."""
    base = local_ref(base_of(unit, units), repo=unit.repo)
    return git(checkouts[unit.repo], "rev-parse", base).stdout.strip()


def hold_for_conflict(
    unit: StoredUnit, store: UnitStore, note: str, log: Callable[[str], None], *, label: str
) -> None:
    """Hold, for a person, a unit whose attempts at a conflict did not settle it (freed by
    `abk release`): the one hold of the conflict handler and the restack lane."""
    store.set_state(
        unit.id,
        HELD,
        note=note,
        held_by=HeldBy.REVIEW,
        cause=Cause.NEEDS_HUMAN,
        pr=unit.pr,
        branch=unit.branch,
    )
    log(f"{label}: {unit.id} held — {note}")
