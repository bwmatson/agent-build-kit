"""Which tier 2 splits are held now: the configuration's `hold` and `tier2-held.json` in the
state directory together, the configuration winning (spec: tier2-holds)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from agent_build_kit.config import Tier2Split
from agent_build_kit.model import Frozen

# The state file's name in the state directory.
HELD_FILE = "tier2-held.json"

# Where a hold comes from.
ORIGIN_CONFIGURATION = "configuration"
ORIGIN_FILE = "file"

# The sources of a file entry; only `gate` carries a deadline.
SOURCE_COMMAND = "command"
SOURCE_GATE = "gate"


class Hold(Frozen):
    """One held split: why, until when, from where, and what the file entry says."""

    split: str
    reason: str
    origins: tuple[str, ...]
    since: datetime | None = None
    until: datetime | None = None
    source: str | None = None
    by: str | None = None


class Holds(Frozen):
    """The splits held now, by name, and what reading the file found."""

    held: dict[str, Hold] = {}
    overridden: tuple[str, ...] = ()
    unreadable: bool = False
    unknown: tuple[str, ...] = ()


def held_splits(splits: tuple[Tier2Split, ...], state_dir: Path, *, now: datetime) -> Holds:
    raise NotImplementedError


def write_hold(
    state_dir: Path,
    split: str,
    *,
    reason: str,
    source: str,
    by: str,
    until: datetime | None = None,
    now: datetime,
) -> None:
    raise NotImplementedError


def remove_hold(state_dir: Path, split: str) -> bool:
    raise NotImplementedError
