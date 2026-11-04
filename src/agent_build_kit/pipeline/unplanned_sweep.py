"""Which `unplanned` units may be swept (spec: unplanned-sweep).

A replan that no longer contains a unit that never started marks it `unplanned` and keeps it, for
the readers of that pass (the replan report, the check for changes a demoted joined unit carried,
the drop preview, the tracker's `removed` state, the planner's context). The store never removes
it, so it grows with every replan. A unit may be swept when all five conditions hold, the first
that fails being the reason it is kept:

1. it holds no work (a branch, pull request, push or approval);
2. no other unit names it in `depends_on`, `needs`, `merge_needs`, `waited_on` or `superseded_by`
   unless the reference can be repointed to its successors (a reference from another unit that is
   itself swept goes with it);
3. its groups are carried by a live unit of its change, or its change is gone or archived;
4. a tick pass has run since it was demoted and, where a tracker is configured, the tracker's last
   successful reconcile is later than the demotion;
5. its change keeps another unit (a change with no unit is never archive-ready), unless it is gone
   or archived.

This module only decides. It removes nothing and writes nothing."""

from __future__ import annotations

from collections.abc import Collection, Sequence
from datetime import UTC, datetime

from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.unit_store import StoredUnit
from agent_build_kit.pipeline.units import CLOSED, UnitState

# The fields of a unit that name another unit.
REFERENCE_FIELDS = ("depends_on", "needs", "merge_needs", "waited_on", "superseded_by")


class Reference(Frozen):
    """One field of `referrer` that names a unit that is swept: to repoint to its successors."""

    referrer: str
    field: str


class Verdict(Frozen):
    """What the sweep decides of one `unplanned` unit: eligible, or the first condition that
    failed. `repoint` are the references from units that stay, to be repointed to `successors`
    before the unit goes."""

    unit: str
    eligible: bool
    reason: str = ""
    repoint: tuple[Reference, ...] = ()
    successors: tuple[str, ...] = ()


def eligibility(
    units: Sequence[StoredUnit],
    *,
    active_changes: Collection[str],
    pass_started: datetime,
    tracker_configured: bool = False,
    tracker_reconciled: datetime | None = None,
) -> dict[str, Verdict]:
    """A verdict for each `unplanned` unit of `units`; a unit in any other state is not one.

    `active_changes` are the changes whose folder exists and is not archived. `pass_started` is
    when the current tick pass began: a unit demoted before it has been seen by a pass.
    `tracker_reconciled` is when the tracker's last successful reconcile ended, None when it
    cannot be read; it matters only when `tracker_configured`."""
    tombstones = {unit.id: unit for unit in units if unit.state == UnitState.UNPLANNED}
    ended = (UnitState.UNPLANNED, UnitState.RETIRED, CLOSED)
    live = [unit for unit in units if unit.state not in ended]
    carried = {
        change: {group for unit in live if unit.change == change for group in unit.groups}
        for change in {unit.change for unit in tombstones.values()}
    }

    def static_reason(unit: StoredUnit) -> str:
        """The first of conditions 1, 3 and 4 that fails, which do not depend on the others."""
        if unit.has_work:
            return "it holds work (a branch, pull request, push or approval)"
        if unit.change in active_changes and not set(unit.groups) <= carried[unit.change]:
            return f"its groups {list(unit.groups)} are carried by no live unit of {unit.change}"
        demoted = _demoted_at(unit)
        if demoted is None:
            return "the time it was demoted cannot be read, so no pass is known to have seen it"
        if demoted >= pass_started:
            return "it was demoted in this pass, which has not finished"
        if tracker_configured:
            if tracker_reconciled is None:
                return "the tracker's last reconcile cannot be read"
            if tracker_reconciled <= demoted:
                return "the tracker has not reconciled since it was demoted"
        return ""

    def references(unit: StoredUnit, removed: Collection[str]) -> list[Reference]:
        """The fields of units that stay (not in `removed`) that name `unit`."""
        return [
            Reference(referrer=other.id, field=field)
            for other in units
            if other.id != unit.id and other.id not in removed
            for field in REFERENCE_FIELDS
            if unit.id in getattr(other, field)
        ]

    # Conditions 1, 3 and 4, then 2 and 5 until they settle: a reference that cannot be repointed
    # keeps its unit, a change's last unit is kept, and each keeps whatever names it only through
    # a unit that stays.
    removable = {uid for uid, unit in tombstones.items() if not static_reason(unit)}
    settled = False
    while not settled:
        settled = True
        for uid in sorted(removable):
            unit = tombstones[uid]
            if references(unit, removable) and not unit.superseded_by:
                removable.discard(uid)
                settled = False
        for change in {tombstones[uid].change for uid in removable}:
            if change in active_changes and all(
                unit.id in removable for unit in units if unit.change == change
            ):
                removable -= {uid for uid in removable if tombstones[uid].change == change}
                settled = False

    def successors_of(unit: StoredUnit) -> tuple[str, ...]:
        """Where a reference to `unit` goes: its successors, each followed on while it is swept
        too, so the reference never lands on a unit that is gone."""
        found: list[str] = []
        for name in unit.superseded_by:
            if name in removable:
                found.extend(n for n in successors_of(tombstones[name]) if n not in found)
            elif name not in found:
                found.append(name)
        return tuple(found)

    def kept_reason(unit: StoredUnit) -> str:
        """The first condition that fails for a unit that is kept, in the order of the five."""
        if unit.has_work:
            return static_reason(unit)
        named = references(unit, removable)
        if named and not unit.superseded_by:
            by = ", ".join(f"{each.referrer} ({each.field})" for each in named)
            return f"it is referenced by {by} and nothing replaced it to repoint them to"
        return static_reason(unit) or f"it is the last unit of {unit.change}"

    found: dict[str, Verdict] = {}
    for uid, unit in tombstones.items():
        if uid not in removable:
            found[uid] = Verdict(unit=uid, eligible=False, reason=kept_reason(unit))
            continue
        stays = tuple(references(unit, removable))
        found[uid] = Verdict(
            unit=uid, eligible=True, repoint=stays, successors=successors_of(unit) if stays else ()
        )
    return found


def _demoted_at(unit: StoredUnit) -> datetime | None:
    """When the unit was demoted to `unplanned`: its last such history entry, None when the
    record has none or an unreadable one. A stamp without an offset is read as UTC."""
    for entry in reversed(unit.history):
        if entry.get("state") == UnitState.UNPLANNED:
            try:
                stamp = datetime.fromisoformat(str(entry["at"]))
            except (KeyError, ValueError):
                return None
            return stamp if stamp.tzinfo else stamp.replace(tzinfo=UTC)
    return None
