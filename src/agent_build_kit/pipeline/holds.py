"""The hold helpers the worker and the orchestrator share (stubs until they move here)."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from agent_build_kit.pipeline.unit_store import Cause, StoredUnit, UnitStore

Claim = Callable[[StoredUnit], None]

OWED_STATES: tuple[str, ...] = ()
OWED_CAUSES: tuple[Cause, ...] = ()
MOVED_BASE_CAUSES: tuple[Cause, ...] = ()


def held_for_its_own_reason(unit: StoredUnit) -> bool:
    raise NotImplementedError


def held_cause(unit: StoredUnit) -> str:
    raise NotImplementedError


def takeover_note(unit: StoredUnit, reason: str = "") -> str:
    raise NotImplementedError


def restore_depth_hold(store: UnitStore, unit: StoredUnit) -> bool:
    raise NotImplementedError


def in_a_lane_run(unit: StoredUnit) -> bool:
    raise NotImplementedError


def read_base_tip(
    checkouts: Mapping[str, Path], unit: StoredUnit, units: Sequence[StoredUnit]
) -> str:
    raise NotImplementedError


def hold_for_conflict(
    unit: StoredUnit, store: UnitStore, note: str, log: Callable[[str], None], *, label: str
) -> None:
    raise NotImplementedError
