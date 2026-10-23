"""The audits of landed units: those awaiting a result and those with one."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from agent_build_kit.pipeline.file_lock import atomic_write_text, file_lock

# In the state directory beside the other state files.
AUDITS = "audits.json"

AWAITING = "awaiting"


class NotAwaitingAudit(Exception):
    """A result was offered for a unit that is not awaiting audit."""


def _write(path: Path, records: dict[str, dict[str, Any]]) -> None:
    atomic_write_text(path, json.dumps(records, indent=2, sort_keys=True))


def record_awaiting(path: Path, *, unit: str, unit_class: str, at: datetime) -> None:
    """Record the unit as awaiting audit."""
    with file_lock(path.with_name(f"{path.name}.lock")):
        records = read_audits(path)
        records[unit] = {"unit_class": unit_class, "state": AWAITING, "at": at.isoformat()}
        _write(path, records)


def record_result(path: Path, *, unit: str, result: str, at: datetime) -> None:
    """Replace the unit's waiting record with `result` (`ok` or `wrong`); raises
    `NotAwaitingAudit` for a unit with no waiting record."""
    with file_lock(path.with_name(f"{path.name}.lock")):
        records = read_audits(path)
        waiting = records.get(unit)
        if waiting is None or waiting.get("state") != AWAITING:
            raise NotAwaitingAudit(f"{unit} is not awaiting audit")
        records[unit] = {**waiting, "state": result, "at": at.isoformat()}
        _write(path, records)


def read_audits(path: Path) -> dict[str, dict[str, Any]]:
    """The records by unit id; empty when there is no file."""
    if not path.exists():
        return {}
    return json.loads(path.read_text())
