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


class UnreadableAudits(Exception):
    """The audit file is there and cannot be read."""


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
    """The records by unit id; empty when there is no file. Raises `UnreadableAudits` for a file
    that is there and cannot be read, so a writer never replaces it."""
    if not path.exists():
        return {}
    try:
        records = json.loads(path.read_text())
    except (OSError, ValueError) as error:
        raise UnreadableAudits(f"{path.name} cannot be read: {error}") from error
    if not isinstance(records, dict):
        raise UnreadableAudits(f"{path.name} does not hold a table of audits")
    return records


def audit_results(path: Path) -> dict[str, str]:
    """The result (`ok` or `wrong`) of each audited unit; empty when the file is missing or
    unreadable."""
    try:
        records = read_audits(path)
    except UnreadableAudits:
        return {}
    return {
        unit: record["state"]
        for unit, record in records.items()
        if isinstance(record, dict) and record.get("state") in ("ok", "wrong")
    }


def audit_status_lines(path: Path) -> list[str]:
    """One line for each unit awaiting audit, with its class."""
    try:
        records = read_audits(path)
    except UnreadableAudits as error:
        return [f"audits: {error}; fix or remove it, audits waiting are not listed"]
    return [
        f"audit waiting: {unit} ({record['unit_class']}) — `abk review audit {unit} ok|wrong`"
        for unit, record in sorted(records.items())
        if record.get("state") == AWAITING
    ]
