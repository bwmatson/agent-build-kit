"""The tick's tracker step and the dirty mark a state change leaves for it (spec: tracker-push)."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.unit_store import StoredUnit


def mark_dirty(state_dir: Path) -> None:
    """Record that a unit changed state since the last pass. Makes no tracker call."""
    raise NotImplementedError


def is_dirty(state_dir: Path) -> bool:
    """Whether a state change is waiting for a pass."""
    raise NotImplementedError


def sync_trackers(
    inst: Installation, units: Sequence[StoredUnit], *, log: Callable[[str], None] = print
) -> None:
    """Push the wanted board of every repo that names a tracker; a repo without one is passed
    over at once, with no call and no file written."""
    raise NotImplementedError
