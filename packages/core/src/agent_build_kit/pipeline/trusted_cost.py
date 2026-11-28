"""Merged changes sorted into trusted, pending, fixed, reverted and unchecked, with their cost."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime
from enum import StrEnum

from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.unit_store import StoredUnit

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
    raise NotImplementedError
