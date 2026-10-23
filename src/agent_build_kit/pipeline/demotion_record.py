"""The demotions of review classes: a runtime override that holds a class at `light`."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

# In the state directory beside the other state files.
DEMOTIONS = "demotions.json"


class UnreadableDemotions(Exception):
    """The demotion file is there and cannot be read."""


class NotDemoted(Exception):
    """A lift was offered for a class that is not demoted."""


def demote(
    path: Path,
    *,
    unit_class: str,
    trigger: str,
    unit: str,
    at: datetime,
    say: Callable[[str], None],
) -> bool:
    """Demote the class, or add the trigger to its standing demotion and say so to `say`;
    whether a new demotion was made."""
    raise NotImplementedError


def lift(path: Path, *, unit_class: str, at: datetime) -> None:
    """Mark the class's standing demotion lifted at `at`; raises `NotDemoted` for a class
    with none."""
    raise NotImplementedError


def read_demotions(path: Path) -> dict[str, dict[str, Any]]:
    """The record of each class by name; empty when there is no file. Raises
    `UnreadableDemotions` for a file that is there and cannot be read."""
    raise NotImplementedError


def demoted_classes(path: Path) -> tuple[str, ...]:
    """The classes whose demotion stands (is not lifted), by name."""
    raise NotImplementedError
