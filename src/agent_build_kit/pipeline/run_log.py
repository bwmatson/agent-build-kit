"""A file per unit run, named for the unit (docs/architecture.md).

The tick prints everything to its own output; this keeps each unit's slice of
it where a person looking for that unit can find it.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from agent_build_kit.pipeline.units import Unit

# How many runs of one unit are kept; older ones go when a new one is written.
RUNS_KEPT = 3


def run_log_dir(state_dir: Path) -> Path:
    """The directory of its own, under the state directory."""
    raise NotImplementedError


def run_log_name(unit: Unit, started: datetime, step: str) -> str:
    """`<change>-<nn>-<YYYYMMDD-HHMMSS>-<step>.log`"""
    raise NotImplementedError


class RunLog:
    """One run's file: a header on open, the unit's lines, an outcome on close."""

    def __init__(
        self, directory: Path, unit: Unit, *, step: str, model: str, base: str, started: datetime
    ) -> None:
        raise NotImplementedError

    @property
    def name(self) -> str:
        raise NotImplementedError

    def emit(self, message: str) -> None:
        raise NotImplementedError

    def close(self, outcome: str) -> None:
        raise NotImplementedError


def remove_change_logs(directory: Path, change: str) -> None:
    """Drop every unit log of a change."""
    raise NotImplementedError
