"""Where a change's folder is: among the active changes, or archived under a dated name."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from agent_build_kit.pipeline.tracker_file import tracker_path
from agent_build_kit.split.select import archive_change_name

ARCHIVE_DIR = "archive"
ARCHIVED_TRACKERS = "tracker-archived"


def archived_entries(changes_dir: Path) -> dict[str, Path]:
    """The archived changes by their undated name, the latest archive of a name winning."""
    archive = changes_dir / ARCHIVE_DIR
    if not archive.is_dir():
        return {}
    return {
        archive_change_name(entry.name): entry
        for entry in sorted(archive.iterdir())
        if entry.is_dir()
    }


def change_folder(changes_dir: Path, name: str, archive: Mapping[str, Path] | None = None) -> Path:
    """The folder of change `name`: the active one, else its archive entry, else the active
    path (which does not exist). A caller asking about many changes passes `archive`, the
    `archived_entries` it read once, so the archive folder is not listed for each."""
    live = changes_dir / name
    if live.is_dir():
        return live
    entries = archived_entries(changes_dir) if archive is None else archive
    return entries.get(name, live)


def tracker_read_dir(
    changes_dir: Path, state_dir: Path, name: str, archive: Mapping[str, Path] | None = None
) -> Path:
    """Where change `name`'s tracker file is read. An archived change's folder is committed with
    the archive, so what a pass records afterwards is kept in a machine-local copy; that copy
    wins over the committed file once it exists."""
    folder = change_folder(changes_dir, name, archive)
    if folder.parent.name != ARCHIVE_DIR:
        return folder
    local = state_dir / ARCHIVED_TRACKERS / folder.name
    return local if tracker_path(local).is_file() else folder


def tracker_write_dir(changes_dir: Path, state_dir: Path, name: str) -> Path:
    """Where change `name`'s tracker file is written: its folder while the change is active, the
    machine-local copy once it is archived, so no tracked file changes after the archive commit."""
    folder = change_folder(changes_dir, name)
    if folder.parent.name != ARCHIVE_DIR:
        return folder
    local = state_dir / ARCHIVED_TRACKERS / folder.name
    local.mkdir(parents=True, exist_ok=True)
    return local
