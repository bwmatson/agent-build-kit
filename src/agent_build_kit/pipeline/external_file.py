"""The hold file of a change: work handed to someone outside the kit (spec: external-work).

`external.yaml` in a change's folder records holds on the whole change or on named groups. The
kit never starts a unit whose groups are all held. The file is read by the planner and the start
path, is not part of the plan hash, and is written only here, under a lock.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Literal

import yaml

from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.file_lock import file_lock
from agent_build_kit.pipeline.work_graph import GROUP_NUMBER

FILE_NAME = "external.yaml"
HELD = "held"
DONE = "done"
RELEASED = "released"

# `all` covers every group of the change's `tasks.md`, those added later too.
Scope = Literal["all"] | tuple[int, ...]


class HoldRefused(ValueError):
    """A hold that cannot be recorded; the message says why."""


class Hold(Frozen):
    """Work handed to `holder`. A status other than the ones above was written by a later
    release and keeps its groups blocked."""

    scope: Scope
    holder: str
    link: str
    since: datetime
    items: dict[str, str | list[str]] = {}
    note: str = ""
    status: str = HELD
    merged_by: str = ""
    done_at: datetime | None = None


def external_path(change_dir: Path) -> Path:
    """Where `change_dir` keeps its holds."""
    return change_dir / FILE_NAME


def read_holds(change_dir: Path) -> tuple[Hold, ...]:
    """The holds of a change, none when it has no file."""
    path = external_path(change_dir)
    if not path.is_file():
        return ()
    loaded = yaml.safe_load(path.read_text()) or {}
    return tuple(Hold.model_validate(raw) for raw in loaded.get("holds", ()))


def write_holds(change_dir: Path, holds: Sequence[Hold]) -> None:
    """Replace the file's holds, under the file's lock."""
    path = external_path(change_dir)
    listed = [hold.model_dump(mode="json") for hold in holds]
    text = yaml.safe_dump({"holds": listed}, sort_keys=False)
    with file_lock(path.with_name(f"{path.name}.lock")):
        path.write_text(text)


def _group_numbers(change_dir: Path) -> tuple[int, ...]:
    tasks = change_dir / "tasks.md"
    if not tasks.is_file():
        return ()
    found = (GROUP_NUMBER.match(line) for line in tasks.read_text().splitlines())
    return tuple(int(match["number"]) for match in found if match)


def _covered(hold: Hold, existing: Sequence[int]) -> frozenset[int]:
    return frozenset(existing) if hold.scope == "all" else frozenset(hold.scope)


def add_hold(change_dir: Path, hold: Hold) -> None:
    """Record `hold`; raises `HoldRefused` for a group the change lacks or one already held."""
    existing = _group_numbers(change_dir)
    covered = _covered(hold, existing)
    for number in sorted(covered - set(existing)):
        raise HoldRefused(f"group {number} does not exist in change {change_dir.name}")
    holds = read_holds(change_dir)
    for other in holds:
        if other.status == RELEASED:
            continue
        for number in sorted(covered & _covered(other, existing)):
            raise HoldRefused(
                f"group {number} of change {change_dir.name} is already held by {other.holder}"
            )
    write_holds(change_dir, [*holds, hold])


def blocked_groups(change_dir: Path) -> frozenset[int]:
    """The groups the kit must leave alone: those of every hold neither done nor released."""
    existing = _group_numbers(change_dir)
    blocked: frozenset[int] = frozenset()
    for hold in read_holds(change_dir):
        if hold.status not in (DONE, RELEASED):
            blocked |= _covered(hold, existing)
    return blocked
