"""The demotions of review classes: a runtime override that holds a class at `light`."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.file_lock import atomic_write_text, file_lock

# In the state directory beside the other state files.
DEMOTIONS = "demotions.json"


class UnreadableDemotions(Exception):
    """The demotion file is there and cannot be read."""


class NotDemoted(Exception):
    """A lift was offered for a class that is not demoted."""


def _write(path: Path, records: dict[str, dict[str, Any]]) -> None:
    atomic_write_text(path, json.dumps(records, indent=2, sort_keys=True))


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
    added = {"trigger": trigger, "unit": unit, "at": at.isoformat()}
    with file_lock(path.with_name(f"{path.name}.lock")):
        records = read_demotions(path)
        standing = records.get(unit_class)
        if standing is not None and standing.get("lifted") is None:
            standing["triggers"].append(added)
            _write(path, records)
            say(f"{unit_class}: already demoted; another trigger, {trigger} on {unit}, recorded")
            return False
        records[unit_class] = {"since": at.isoformat(), "lifted": None, "triggers": [added]}
        _write(path, records)
        return True


def lift(path: Path, *, unit_class: str, at: datetime) -> None:
    """Mark the class's standing demotion lifted at `at`; raises `NotDemoted` for a class
    with none."""
    with file_lock(path.with_name(f"{path.name}.lock")):
        records = read_demotions(path)
        standing = records.get(unit_class)
        if standing is None or standing.get("lifted") is not None:
            raise NotDemoted(f"{unit_class} is not demoted")
        standing["lifted"] = at.isoformat()
        _write(path, records)


def read_demotions(path: Path) -> dict[str, dict[str, Any]]:
    """The record of each class by name; empty when there is no file. Raises
    `UnreadableDemotions` for a file that is there and cannot be read."""
    if not path.exists():
        return {}
    try:
        records = json.loads(path.read_text())
    except (OSError, ValueError) as error:
        raise UnreadableDemotions(f"{path.name} cannot be read: {error}") from error
    if not isinstance(records, dict):
        raise UnreadableDemotions(f"{path.name} does not hold a table of demotions")
    return records


class Standing(Frozen):
    """A demotion that stands: the class, the trigger that made it, its unit and since when."""

    name: str
    trigger: str
    unit: str
    since: str


def standing_demotions(path: Path) -> list[Standing]:
    """The demotions that stand (are not lifted), by class name. Raises `UnreadableDemotions`
    for a file that cannot be read and for a standing record that is malformed, so no caller
    reads a broken file as no demotion."""
    standing = []
    for name, record in sorted(read_demotions(path).items()):
        if not isinstance(record, dict):
            raise UnreadableDemotions(f"{path.name} holds a malformed record for {name}")
        if record.get("lifted") is not None:
            continue
        try:
            first = record["triggers"][0]
            standing.append(
                Standing(
                    name=name,
                    trigger=first["trigger"],
                    unit=first["unit"],
                    since=record["since"],
                )
            )
        except (KeyError, IndexError, TypeError, ValueError) as error:
            raise UnreadableDemotions(
                f"{path.name} holds a malformed record for {name}: {error!r}"
            ) from error
    return standing


def demotion_status_lines(path: Path) -> list[str]:
    """One line for each class whose demotion stands, with its trigger, the unit and since when;
    one line saying so when the file cannot be read."""
    try:
        standing = standing_demotions(path)
    except UnreadableDemotions as error:
        return [f"demotions: {error}; fix or remove it, demoted classes are not listed"]
    return [
        f"demoted: {d.name} by {d.trigger} on {d.unit} since {d.since}"
        f" — `abk review reinstate {d.name}` lifts it"
        for d in standing
    ]


def demoted_classes(path: Path) -> tuple[str, ...]:
    """The classes whose demotion stands (is not lifted), by name. Raises `UnreadableDemotions`
    for a file that cannot be read: a caller that lands or classifies a unit holds the unit
    back then, so a broken file never lifts a demotion by being unread."""
    return tuple(d.name for d in standing_demotions(path))
