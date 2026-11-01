"""Mirroring archived changes onto a board, a capped few per run (spec: tracker-push)."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path

from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.units import Unit


class BackfillReport(Frozen):
    """`created` counts the items made; `listed` holds the markers a dry run would create."""

    created: int = 0
    listed: tuple[str, ...] = ()


def backfill(
    repo: str,
    *,
    changes_dir: Path,
    changes: Sequence[str],
    units: Sequence[Unit],
    repo_url: str,
    state_dir: Path,
    cap: int,
    dry_run: bool = False,
    log: Callable[[str], None] = print,
) -> BackfillReport:
    """Mirror archived `changes` as closed change items, done group items and, with a `task`
    level, done task items: at most `cap` creates a run; a dry run lists them and writes
    nothing."""
    raise NotImplementedError
