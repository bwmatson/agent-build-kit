"""The audits of landed units: those awaiting a result and those with one."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

# In the state directory beside the other state files.
AUDITS = "audits.json"


class NotAwaitingAudit(Exception):
    """A result was offered for a unit that is not awaiting audit."""


def record_awaiting(path: Path, *, unit: str, unit_class: str, at: datetime) -> None:
    """Record the unit as awaiting audit."""
    raise NotImplementedError


def record_result(path: Path, *, unit: str, result: str, at: datetime) -> None:
    """Replace the unit's waiting record with `result` (`ok` or `wrong`); raises
    `NotAwaitingAudit` for a unit with no waiting record."""
    raise NotImplementedError


def read_audits(path: Path) -> dict[str, dict[str, Any]]:
    """The records by unit id; empty when there is no file."""
    raise NotImplementedError
