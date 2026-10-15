"""Which runtimes are blocked now: the configuration's lists and `tier2-blocked.json` in the
state directory together, the configuration winning (spec: tier2-runtime-blocks).

The file holds one entry per runtime. Reading never changes it, so an expired entry stays
until the next write; a file that cannot be read blocks nothing, as an unreadable pause
marker pauses nothing.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from pydantic import TypeAdapter, ValidationError

from agent_build_kit.config import WorkspaceConfig, known_runtime_names
from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.file_lock import atomic_write_text, file_lock

# The state file's name in the state directory.
BLOCKED_FILE = "tier2-blocked.json"

# Where a block comes from.
ORIGIN_CONFIGURATION = "configuration"
ORIGIN_FILE = "file"

# The source of a block set by hand, which never has a deadline.
SOURCE_COMMAND = "command"


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


class _Entry(Frozen):
    reason: str
    since: datetime
    until: datetime | None = None
    source: str
    by: str


_ENTRIES = TypeAdapter(dict[str, _Entry])


def _read(path: Path) -> dict[str, _Entry] | None:
    """The file's entries; None when it cannot be read, empty when it is not there."""
    try:
        return _ENTRIES.validate_json(path.read_text())
    except FileNotFoundError:
        return {}
    except (OSError, ValueError, ValidationError):
        return None


def blocked_runtimes(config: WorkspaceConfig, state_dir: Path, *, now: datetime) -> Blocks:
    """The runtimes blocked at `now`; reads, and changes nothing on disk."""
    entries = _read(state_dir / BLOCKED_FILE)
    known = known_runtime_names(config.runtimes)
    allowed = set(config.tests.runtimes_allowed)
    blocked: dict[str, Block] = {
        name: Block(
            runtime=name,
            reason="listed in tests.runtimes_blocked",
            origins=(ORIGIN_CONFIGURATION,),
        )
        for name in config.tests.runtimes_blocked
    }
    overridden: list[str] = []
    unknown: list[str] = []
    for name, entry in sorted((entries or {}).items()):
        if name not in known:
            unknown.append(name)
            continue
        if entry.until is not None and entry.until <= now:
            continue
        if name in allowed:
            overridden.append(name)
            continue
        held = blocked.get(name)
        blocked[name] = Block(
            runtime=name,
            reason=entry.reason,
            origins=(*(held.origins if held else ()), ORIGIN_FILE),
            since=entry.since,
            until=entry.until,
            source=entry.source,
            by=entry.by,
        )
    return Blocks(
        blocked=dict(sorted(blocked.items())),
        overridden=tuple(overridden),
        unreadable=entries is None,
        unknown=tuple(unknown),
    )


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
    if source == SOURCE_COMMAND and until is not None:
        raise ValueError(f"a block with the source {SOURCE_COMMAND!r} has no deadline")
    path = state_dir / BLOCKED_FILE
    entry = _Entry(reason=reason, since=now, until=until, source=source, by=by)
    with file_lock(path.with_name(f"{path.name}.lock")):
        # An unreadable file is replaced: nothing can read back what it held.
        entries = _read(path) or {}
        entries[runtime] = entry
        atomic_write_text(path, _ENTRIES.dump_json(entries, indent=2).decode() + "\n")
