"""Finding the nearest file or folder above a path, the nearest existing folder of a path, and the
git checkout a path is in: one implementation, importing no other kit module."""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path

GIT_TIMEOUT_SECONDS = 10


def find_up(
    names: Sequence[str],
    start: Path,
    *,
    stop: Path,
    outermost: bool = False,
    accept: Callable[[Path], bool] | None = None,
) -> Path | None:
    """The entry named in `names` in the nearest folder from `start` up to and including `stop`
    (the match nearest `stop` when `outermost`); None when there is none."""
    origin = nearest_existing(start)
    if origin is None or stop not in (origin, *origin.parents):
        return None
    found: Path | None = None
    for folder in (origin, *origin.parents):
        for name in names:
            candidate = folder / name
            if candidate.exists() and (accept is None or accept(candidate)):
                if not outermost:
                    return candidate
                found = candidate
                break
        if folder == stop:
            break
    return found


def nearest_existing(path: Path) -> Path | None:
    """`path` for a folder, its folder for a file, else its nearest existing ancestor."""
    existing = path
    while not existing.exists():
        if existing.parent == existing:
            return None
        existing = existing.parent
    return existing if existing.is_dir() else existing.parent


def checkout_root(path: Path) -> Path | None:
    """The git working-tree root of `path`; None outside a repository or without git."""
    folder = nearest_existing(path)
    if folder is None:
        return None
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=folder,
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT_SECONDS,
            check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    top = result.stdout.strip()
    return Path(top).resolve() if top else None
