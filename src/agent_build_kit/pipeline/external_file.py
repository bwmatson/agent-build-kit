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

from agent_build_kit.model import Frozen

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
    raise NotImplementedError


def read_holds(change_dir: Path) -> tuple[Hold, ...]:
    """The holds of a change, none when it has no file."""
    raise NotImplementedError


def write_holds(change_dir: Path, holds: Sequence[Hold]) -> None:
    """Replace the file's holds, under the file's lock."""
    raise NotImplementedError


def add_hold(change_dir: Path, hold: Hold) -> None:
    """Record `hold`; raises `HoldRefused` for a group the change lacks or one already held."""
    raise NotImplementedError


def blocked_groups(change_dir: Path) -> frozenset[int]:
    """The groups the kit must leave alone: those of every hold neither done nor released."""
    raise NotImplementedError
