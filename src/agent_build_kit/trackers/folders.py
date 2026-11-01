"""Where a change's folder is: among the active changes, or archived under a dated name."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.split.select import archive_change_name

ARCHIVE_DIR = "archive"


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


def change_folder(changes_dir: Path, name: str) -> Path:
    """The folder of change `name`: the active one, else its archive entry, else the active
    path (which does not exist)."""
    live = changes_dir / name
    if live.is_dir():
        return live
    return archived_entries(changes_dir).get(name, live)
