"""What the resolution lanes record on disk, and how a reader says what a unit is resolving.

The dispatcher, `abk explain` and a worker all read and write these records, so they sit in
the core; the lane's decisions stay in `resolution_lane`."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from agent_build_kit.pipeline.unit_store import StoredUnit
from agent_build_kit.pipeline.units import ProjectKey


def resolving_phrase(kind: str, base: str) -> str:
    """How the status and `abk explain` say what a unit is resolving."""
    raise NotImplementedError


def record_path(state_dir: Path, key: ProjectKey) -> Path:
    """Where the lane of a project says what it holds."""
    raise NotImplementedError


def lane_record(state_dir: Path) -> list[dict[str, str]]:
    """What the lanes of a live tick hold."""
    raise NotImplementedError


def write_worker_record(
    state_dir: Path, key: ProjectKey, unit: StoredUnit, *, base: str, pid: int | None = None
) -> Path:
    """Say that a resolve worker runs `unit`'s resolution run."""
    raise NotImplementedError


def clear_worker_record(path: Path) -> None:
    """Remove a record `write_worker_record` wrote."""
    raise NotImplementedError


def record_deferral(state_dir: Path, unit_id: str, resume_at: datetime) -> None:
    """Say that a refusal defers `unit_id`'s resolution run until `resume_at`."""
    raise NotImplementedError


def clear_deferral(state_dir: Path, unit_id: str) -> None:
    """Forget the recorded deferral of `unit_id`'s run."""
    raise NotImplementedError


def deferred_until(state_dir: Path, unit_id: str) -> datetime | None:
    """When the recorded deferral of `unit_id`'s run ends, or None."""
    raise NotImplementedError


def lane_held_by_record(state_dir: Path) -> set[str]:
    """The ids of the units the lanes of a live tick hold."""
    raise NotImplementedError
