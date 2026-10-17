"""The emergency lane's record: which priority-0 units use the lane's cap.

A unit started past the normal limits stays in the lane until it finishes. Each project keeps
a small record of its lane's units in the state directory, written before the unit's build is
submitted, read as the lane use, and pruned of units that are no longer in progress.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from pathlib import Path

from agent_build_kit.pipeline.file_lock import atomic_write_text
from agent_build_kit.pipeline.units import Unit, in_progress, project_key


def lane_dir(state_dir: Path) -> Path:
    """The directory of its own, under the state directory: one record for each project."""
    return state_dir / "emergency-lane"


def _record(state_dir: Path, unit: Unit) -> Path:
    key = project_key(unit)
    return lane_dir(state_dir) / (
        re.sub(r"[^A-Za-z0-9._-]+", "_", f"{key.repo}__{key.project}") + ".json"
    )


def _read(path: Path) -> list[str]:
    try:
        found = json.loads(path.read_text())
    except (OSError, ValueError):
        return []
    return [item for item in found if isinstance(item, str)] if isinstance(found, list) else []


def _write(path: Path, ids: Sequence[str]) -> None:
    if ids:
        atomic_write_text(path, json.dumps(sorted(ids)))
    else:
        path.unlink(missing_ok=True)


def lane_units(state_dir: Path) -> frozenset[str]:
    """The ids of the units the lanes of every project record."""
    return frozenset(
        unit_id for path in sorted(lane_dir(state_dir).glob("*.json")) for unit_id in _read(path)
    )


def enter(state_dir: Path, unit: Unit) -> None:
    """Record `unit` in its project's lane."""
    path = _record(state_dir, unit)
    ids = _read(path)
    if unit.id not in ids:
        _write(path, [*ids, unit.id])


def prune(state_dir: Path, units: Sequence[Unit]) -> None:
    """Drop from the records each unit that is not in progress in `units`, or is not there."""
    live = {unit.id for unit in units if in_progress(unit, units)}
    for path in lane_dir(state_dir).glob("*.json"):
        ids = _read(path)
        kept = [unit_id for unit_id in ids if unit_id in live]
        if kept != ids:
            _write(path, kept)
