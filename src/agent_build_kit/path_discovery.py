"""Finding the nearest file or folder above a path, the nearest existing folder of a path, and the
git checkout a path is in: one implementation, importing no other kit module."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path


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
    raise NotImplementedError


def nearest_existing(path: Path) -> Path | None:
    """`path` for a folder, its folder for a file, else its nearest existing ancestor."""
    raise NotImplementedError


def checkout_root(path: Path) -> Path | None:
    """The git working-tree root of `path`; None outside a repository or without git."""
    raise NotImplementedError
