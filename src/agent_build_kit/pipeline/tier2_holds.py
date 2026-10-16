"""Which tier 2 splits are held now: the configuration's `hold` and `tier2-held.json` in the
state directory together, the configuration winning (spec: tier2-holds)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from pydantic import AwareDatetime, TypeAdapter, ValidationError

from agent_build_kit.config import REST_SPLIT, Tier2Split, WorkspaceConfig, tier2_splits
from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.file_lock import atomic_write_text, file_lock

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
    # Splits whose file entry the configuration's `hold: false` overrode.
    overridden: tuple[str, ...] = ()
    # The file exists and could not be read.
    unreadable: bool = False
    # Splits a file entry named that nothing declares.
    unknown: tuple[str, ...] = ()


class _Entry(Frozen):
    reason: str
    # Aware only: a naive time cannot be compared with the clock, and a file holding one
    # reads as unreadable.
    since: AwareDatetime
    until: AwareDatetime | None = None
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


def held_splits(splits: tuple[Tier2Split, ...], state_dir: Path, *, now: datetime) -> Holds:
    """The splits held at `now`; reads, and changes nothing on disk, so an expired entry stays
    in the file until the next write. A file that cannot be read holds nothing."""
    entries = _read(state_dir / HELD_FILE)
    known = {split.name for split in splits}
    held: dict[str, Hold] = {
        split.name: Hold(
            split=split.name,
            reason="`hold: true` in tests.e2e_splits",
            origins=(ORIGIN_CONFIGURATION,),
        )
        for split in splits
        if split.hold is True
    }
    released = {split.name for split in splits if split.hold is False}
    overridden: list[str] = []
    unknown: list[str] = []
    for name, entry in sorted((entries or {}).items()):
        if name not in known:
            unknown.append(name)
            continue
        if entry.until is not None and entry.until <= now:
            continue
        if name in released:
            overridden.append(name)
            continue
        configured = held.get(name)
        held[name] = Hold(
            split=name,
            reason=entry.reason,
            origins=(*(configured.origins if configured else ()), ORIGIN_FILE),
            since=entry.since,
            until=entry.until,
            source=entry.source,
            by=entry.by,
        )
    return Holds(
        held=dict(sorted(held.items())),
        overridden=tuple(overridden),
        unreadable=entries is None,
        unknown=tuple(unknown),
    )


def declared_splits(config: WorkspaceConfig) -> tuple[Tier2Split, ...]:
    """Every split any repo declares, by name, the first declaration of a name winning, and
    `rest` last."""
    found: dict[str, Tier2Split] = {}
    for repo in config.repos.values():
        for split in tier2_splits(repo, config):
            found.setdefault(split.name, split)
    named = [split for name, split in found.items() if name != REST_SPLIT]
    return (*named, found.get(REST_SPLIT, Tier2Split(name=REST_SPLIT)))


def hold_text(hold: Hold) -> str:
    """What holds a split, in words: the reason, the deadline and where the hold is written."""
    until = f"until {hold.until:%Y-%m-%d %H:%M} UTC" if hold.until else "no deadline"
    source = f", source {hold.source}" if hold.source else ""
    return f"{hold.reason} ({until}{source}, origin {' and '.join(hold.origins)})"


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
    """Write `split`'s entry atomically under a lock, replacing an earlier one. A deadline
    is refused (ValueError) for any source but `gate`."""
    if until is not None and source != SOURCE_GATE:
        raise ValueError(
            f"a hold with the source {source!r} has no deadline; only {SOURCE_GATE!r} does"
        )
    path = state_dir / HELD_FILE
    entry = _Entry(reason=reason, since=now, until=until, source=source, by=by)
    with file_lock(path.with_name(f"{path.name}.lock")):
        # An unreadable file is replaced: nothing can read back what it held.
        entries = _read(path) or {}
        entries[split] = entry
        atomic_write_text(path, _ENTRIES.dump_json(entries, indent=2).decode() + "\n")


def remove_hold(state_dir: Path, split: str) -> bool:
    """Remove `split`'s entry under the lock; False when there was none. A file that cannot
    be read raises ValueError rather than saying there was nothing to remove."""
    path = state_dir / HELD_FILE
    if not path.exists():
        return False
    with file_lock(path.with_name(f"{path.name}.lock")):
        entries = _read(path)
        if entries is None:
            raise ValueError(f"{path} cannot be read; fix or remove it")
        if split not in entries:
            return False
        del entries[split]
        atomic_write_text(path, _ENTRIES.dump_json(entries, indent=2).decode() + "\n")
        return True
