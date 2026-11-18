"""What the resolution lanes record on disk, and how a reader says what a unit is resolving.

The dispatcher, `abk explain` and a worker all read and write these records, so they sit in
the core; the lane's decisions stay in `resolution_lane`."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime
from pathlib import Path

from agent_build_kit.pipeline import host, spans
from agent_build_kit.pipeline.file_lock import atomic_write_text
from agent_build_kit.pipeline.unit_store import StoredUnit
from agent_build_kit.pipeline.units import ProjectKey
from agent_build_kit.pipeline.workspaces import holder_alive

# Each project's lane writes its record (`record_path`) in the state directory, for `abk status`
# and the graph page, which are not the process that runs the tick. The glob also reads the
# single record a tick of the previous version left as `restacks.json`.
RECORD_GLOB = "restacks*.json"


def resolving_phrase(kind: str, base: str) -> str:
    """How the status and `abk explain` say what a unit is resolving."""
    return "resolving a comment" if kind == "comment" else f"resolving base {base}"


def record_path(state_dir: Path, key: ProjectKey) -> Path:
    """Where the lane of a project says what it holds, beside the other lanes' records."""
    name = f"{key.repo}/{key.project}".encode()
    return state_dir / f"restacks-{hashlib.sha256(name).hexdigest()[:12]}.json"


def lane_record(state_dir: Path) -> list[dict[str, str]]:
    """What the lanes of a live tick hold: each unit's `unit`, `base`, `status` (running or
    waiting) and `since`. A record whose process has gone is not trusted: nothing is held."""
    held: list[dict[str, str]] = []
    for path in sorted(state_dir.glob(RECORD_GLOB)):
        try:
            record = json.loads(path.read_text())
            pid, units = record["pid"], record["units"]
        except (OSError, ValueError, KeyError, TypeError):
            continue
        if isinstance(pid, int) and holder_alive(pid, record.get("host")):
            held.extend(entry for entry in units if isinstance(entry, dict))
    return held


def write_worker_record(
    state_dir: Path, key: ProjectKey, unit: StoredUnit, *, base: str, pid: int | None = None
) -> Path:
    """Say that the process `pid` (this one), a resolve worker, runs `unit`'s resolution run:
    the record the lanes of a tick write (`record_path`), so the run is read as the lane's
    (`lane_record`) while the process lives. Returns the record's path for
    `clear_worker_record`."""
    pid = os.getpid() if pid is None else pid
    # One file for each worker of the project: workers never overwrite or remove each other's.
    base_path = record_path(state_dir, key)
    path = base_path.with_name(f"{base_path.stem}-{pid}{base_path.suffix}")
    entry = {
        "unit": unit.id,
        "base": base,
        "resolving": unit.resolving,
        "status": "running",
        "since": spans.clock.now().isoformat(),
    }
    atomic_write_text(path, json.dumps({"pid": pid, "host": host.this_host(), "units": [entry]}))
    return path


def clear_worker_record(path: Path) -> None:
    """Remove a record `write_worker_record` wrote: the run it named has ended."""
    path.unlink(missing_ok=True)


def record_deferral(state_dir: Path, unit_id: str, resume_at: datetime) -> None:
    """Say that a refusal (a usage pause, a login) defers `unit_id`'s resolution run until
    `resume_at`: the dispatch starts no resolve worker for it before then."""
    path = _deferral_path(state_dir, unit_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, json.dumps({"unit": unit_id, "until": resume_at.isoformat()}))


def clear_deferral(state_dir: Path, unit_id: str) -> None:
    """Forget the recorded deferral of `unit_id`'s run: a worker has taken the run up."""
    _deferral_path(state_dir, unit_id).unlink(missing_ok=True)


def deferred_until(state_dir: Path, unit_id: str) -> datetime | None:
    """When the recorded deferral of `unit_id`'s run ends, or None when none is recorded."""
    try:
        record = json.loads(_deferral_path(state_dir, unit_id).read_text())
        return datetime.fromisoformat(record["until"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _deferral_path(state_dir: Path, unit_id: str) -> Path:
    name = hashlib.sha256(unit_id.encode()).hexdigest()[:16]
    return state_dir / "resolution-deferrals" / f"{name}.json"


def lane_held_by_record(state_dir: Path) -> set[str]:
    """The ids of the units the lanes of a live tick hold, running or waiting (`lane_record`)."""
    return {entry["unit"] for entry in lane_record(state_dir)}
