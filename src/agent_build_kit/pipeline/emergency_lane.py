"""The emergency lane's record: which priority-0 units use the lane's cap.

A unit started past the normal limits stays in the lane until it finishes. Each project keeps
a small record of its lane's units in the state directory, written before the unit's build is
submitted, read as the lane use, and pruned of units that are no longer in progress.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from agent_build_kit.pipeline.units import Unit


def lane_units(state_dir: Path) -> frozenset[str]:
    """The ids of the units the lanes of every project record."""
    raise NotImplementedError


def enter(state_dir: Path, unit: Unit) -> None:
    """Record `unit` in its project's lane."""
    raise NotImplementedError


def prune(state_dir: Path, units: Sequence[Unit]) -> None:
    """Drop from the records each unit that is not in progress in `units`, or is not there."""
    raise NotImplementedError
