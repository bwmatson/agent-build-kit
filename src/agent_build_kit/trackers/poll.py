"""Reads the changes people made on a repo's board since the last poll (spec: tracker-pull)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from agent_build_kit.trackers.base import Change


def poll_board(
    repo: str, *, state_dir: Path, log: Callable[[str], None] = print
) -> tuple[Change, ...]:
    """The changes to `repo`'s board that the kit did not write and has not reported before.

    Records the cursor and the revisions seen in the repo's machine-local snapshot. The first
    poll with no cursor only records; a failed poll is logged and backs the next ones off."""
    raise NotImplementedError
