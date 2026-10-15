"""Which runtimes are blocked now: the configuration's lists and `tier2-blocked.json` in the
state directory together, the configuration winning (spec: tier2-runtime-blocks)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from agent_build_kit.config import WorkspaceConfig
from agent_build_kit.model import Frozen

# The state file's name in the state directory.
BLOCKED_FILE = "tier2-blocked.json"

# Where a block comes from.
ORIGIN_CONFIGURATION = "configuration"
ORIGIN_FILE = "file"


class Block(Frozen):
    """One blocked runtime: why, until when, from where, and what the file entry says."""

    runtime: str
    reason: str
    origins: tuple[str, ...]
    since: datetime | None = None
    until: datetime | None = None
    source: str | None = None
    by: str | None = None


class Blocks(Frozen):
    """The runtimes blocked now, by runtime name, and what reading the file found."""

    blocked: dict[str, Block] = {}
    # Runtimes whose file entry the configuration's allowed list overrode.
    overridden: tuple[str, ...] = ()
    # The file exists and could not be read.
    unreadable: bool = False
    # Runtimes a file entry named that nothing knows.
    unknown: tuple[str, ...] = ()


def blocked_runtimes(config: WorkspaceConfig, state_dir: Path, *, now: datetime) -> Blocks:
    """The runtimes blocked at `now`; reads, and changes nothing on disk."""
    raise NotImplementedError


def write_block(
    state_dir: Path,
    runtime: str,
    *,
    reason: str,
    source: str,
    by: str,
    until: datetime | None = None,
    now: datetime,
) -> None:
    """Write `runtime`'s entry atomically under a lock, replacing an earlier one. A deadline
    is refused (ValueError) for the source `command`."""
    raise NotImplementedError
