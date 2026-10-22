"""The admission records: why a unit was admitted or held at a slot, written beside the
decision log (spec: capacity-checks, admission leaves a record that explains it)."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Literal

from agent_build_kit.config import CONFIG_FILENAME, overlay_path
from agent_build_kit.installation import Installation
from agent_build_kit.model import Frozen

# The admission records, in the state directory.
ADMISSIONS_NAME = "admissions.jsonl"

# The `kind` of a line that holds a tick's counts rather than one admission.
COUNTS = "counts"


class Counted(Frozen):
    """A unit counted in a slot, and why it counts: its state, and the pull request, branch or
    pushed commit that makes it so."""

    id: str
    state: str
    why: str


class UsageFacts(Frozen):
    """The unit's own account's usage decision, as made. `may_start` is None when the round did
    not ask the guard about the account, because none of its units came up for a start."""

    may_start: bool | None
    reason: str
    source: str = ""
    age_seconds: float | None = None
    threshold: float | None = None
    ramp: float | None = None
    estimate: bool = False
    estimate_starts: int = 0


class AdmissionRecord(Frozen):
    """One admission (`admitted`), one wait for a slot (`slot`) or one refusal by the unit's own
    account (`usage`). The slot is the account's label (`default` for the default account), or
    the project's tag when units are counted per project."""

    at: datetime
    kind: Literal["admitted", "slot", "usage"]
    unit: str
    tick: str
    slot: str
    limit: int
    counted: tuple[Counted, ...]
    usage: UsageFacts
    fingerprint: str


class SlotCount(Frozen):
    """What one slot counted in a tick: the ids, the limit and the room left."""

    slot: str
    limit: int
    ids: tuple[str, ...]
    room: int


class TickCounts(Frozen):
    """The per-slot counts of a tick that started or refused a unit."""

    at: datetime
    tick: str
    fingerprint: str
    slots: tuple[SlotCount, ...]


def append_admission(path: Path, record: AdmissionRecord) -> None:
    """Add `record` to the file at `path`."""
    _append(path, json.loads(record.model_dump_json()))


def append_counts(path: Path, counts: TickCounts) -> None:
    """Add `counts` to the file at `path`."""
    _append(path, {"kind": COUNTS, **json.loads(counts.model_dump_json())})


def _append(path: Path, line: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as log:
        log.write(json.dumps(line) + "\n")


def _lines(path: Path) -> list[dict]:
    try:
        text = path.read_text()
    except OSError:
        return []
    found: list[dict] = []
    for line in text.splitlines():
        try:
            raw = json.loads(line)
        except ValueError:
            continue
        if isinstance(raw, dict):
            found.append(raw)
    return found


def read_admissions(path: Path) -> list[AdmissionRecord]:
    """The admission, slot-wait and usage-refusal records in the file at `path`, oldest first."""
    found: list[AdmissionRecord] = []
    for raw in _lines(path):
        if raw.get("kind") == COUNTS:
            continue
        try:
            found.append(AdmissionRecord.model_validate(raw))
        except ValueError:
            continue
    return found


def read_counts(path: Path) -> list[TickCounts]:
    """The per-tick counts in the file at `path`, oldest first."""
    found: list[TickCounts] = []
    for raw in _lines(path):
        if raw.get("kind") != COUNTS:
            continue
        try:
            found.append(TickCounts.model_validate({k: v for k, v in raw.items() if k != "kind"}))
        except ValueError:
            continue
    return found


def _mtime(path: Path) -> int:
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return 0


def config_fingerprint(inst: Installation) -> str:
    """A hash of the installation's merged configuration and the modification times of
    `abk.yaml` and `abk.local.yaml`."""
    base = inst.root / CONFIG_FILENAME
    parts = [inst.config.model_dump_json(), str(_mtime(base)), str(_mtime(overlay_path(base)))]
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()[:12]
