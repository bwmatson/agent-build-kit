"""Merged changes sorted into trusted, pending, fixed, reverted and unchecked, with their cost."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime, timedelta
from enum import StrEnum

from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.archive import change_merged_at, is_ready_to_archive
from agent_build_kit.pipeline.unit_store import StoredUnit
from agent_build_kit.pipeline.units import UnitState

# Given a merged unit and the bound for its search (its own latest `merged` stamp plus `days`):
# whether its merge was reverted, or None when the unit cannot be searched.
RevertLookup = Callable[[StoredUnit, datetime], bool | None]


class Verdict(StrEnum):
    TRUSTED = "trusted"
    PENDING = "pending"
    FIXED = "fixed"
    REVERTED = "reverted"
    UNCHECKED = "unchecked"


class JudgedChange(Frozen):
    """A merged change: when it merged, its verdict, every reason that holds, and its cost
    (None when no call recorded one)."""

    change: str
    merged_at: datetime
    verdict: Verdict
    reasons: tuple[str, ...] = ()
    cost: float | None = None


class Window(Frozen):
    """The trusted changes merged in one window of `days` days."""

    trusted: int
    uncosted: int
    cost: float
    cost_per_trusted_change: float | None


class TrustedChanges(Frozen):
    changes: tuple[JudgedChange, ...]
    latest: Window
    previous: Window
    pending_count: int
    pending_cost: float
    unchecked: tuple[str, ...]


def sort_changes(
    units: list[StoredUnit],
    costs: Mapping[str, float | None],
    revert_lookup: RevertLookup,
    *,
    now: datetime,
    days: int,
) -> TrustedChanges:
    """Each merged change with its verdict and cost, and the two windows' figures."""
    span = timedelta(days=days)
    names = sorted({member.change for unit in units for member in unit.members()})
    judged: list[JudgedChange] = []
    for change in names:
        if not is_ready_to_archive(change, units):
            continue
        stamp = change_merged_at(change, units)
        if not stamp:
            continue
        merged_at = datetime.fromisoformat(stamp)
        verdict, reasons = _verdict(change, units, revert_lookup, merged_at, now, span)
        judged.append(
            JudgedChange(
                change=change,
                merged_at=merged_at,
                verdict=verdict,
                reasons=reasons,
                cost=costs.get(change),
            )
        )

    def window(newest: int) -> Window:
        """The trusted changes merged in the `days` days ending `newest` windows before now."""
        end, start = now - span * newest, now - span * (newest + 1)
        inside = [c for c in judged if c.verdict == Verdict.TRUSTED and start < c.merged_at <= end]
        costed = [c.cost for c in inside if c.cost is not None]
        total = sum(costed)
        return Window(
            trusted=len(costed),
            uncosted=len(inside) - len(costed),
            cost=total,
            cost_per_trusted_change=total / len(costed) if costed else None,
        )

    pending = [c for c in judged if c.verdict == Verdict.PENDING]
    return TrustedChanges(
        changes=tuple(judged),
        latest=window(1),
        previous=window(2),
        pending_count=len(pending),
        pending_cost=sum(c.cost for c in pending if c.cost is not None),
        unchecked=tuple(c.change for c in judged if c.verdict == Verdict.UNCHECKED),
    )


def _stamp(unit: StoredUnit) -> datetime | None:
    """The unit's latest `merged` stamp."""
    stamps = [e["at"] for e in unit.history if e.get("state") == "merged" and e.get("at")]
    return datetime.fromisoformat(max(stamps)) if stamps else None


def _verdict(
    change: str,
    units: list[StoredUnit],
    revert_lookup: RevertLookup,
    merged_at: datetime,
    now: datetime,
    span: timedelta,
) -> tuple[Verdict, tuple[str, ...]]:
    if now - merged_at < span:
        return Verdict.PENDING, ()
    mine = [u for u in units if u.carries(change)]
    ids = {u.id for u in mine}
    fixed: list[str] = []
    for unit in mine:
        if any(e.get("cause") == "late_failure" for e in unit.history):
            fixed.append(f"late_failure: {unit.id}")
        if any(p.role == "late-fix" for p in unit.pulls):
            fixed.append(f"late-fix pull request: {unit.id}")
    for unit in units:
        if not unit.change.startswith(("fix-", "hotfix-")):
            continue
        if unit.state in (UnitState.RETIRED, UnitState.UNPLANNED) or not ids & set(unit.needs):
            continue
        began = datetime.fromisoformat(unit.history[0]["at"]) if unit.history else now
        if merged_at <= began <= merged_at + span:
            fixed.append(f"fix unit: {unit.id}")
    reverted: list[str] = []
    unchecked: list[str] = []
    for unit in mine:
        stamp = _stamp(unit)
        if unit.state != UnitState.MERGED or stamp is None:
            continue
        found = revert_lookup(unit, stamp + span)
        if found:
            reverted.append(f"reverted: {unit.id}")
        elif found is None:
            unchecked.append(f"unchecked: {unit.id}")
    reasons = (*fixed, *reverted, *unchecked)
    if fixed:
        return Verdict.FIXED, reasons
    if reverted:
        return Verdict.REVERTED, reasons
    if unchecked:
        return Verdict.UNCHECKED, reasons
    return Verdict.TRUSTED, reasons
