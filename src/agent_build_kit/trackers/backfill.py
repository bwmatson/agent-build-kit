"""Mirroring archived changes onto a board, a capped few per run (spec: tracker-push)."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path

from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.units import Unit
from agent_build_kit.trackers.reconciler import reconcile


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
    browse: Callable[[str], str],
    state_dir: Path,
    cap: int,
    dry_run: bool = False,
    log: Callable[[str], None] = print,
) -> BackfillReport:
    """Mirror archived `changes` as closed change items, done group items and, with a `task`
    level, done task items: at most `cap` creates a run; a dry run lists them and writes
    nothing."""
    report = reconcile(
        repo,
        changes_dir=changes_dir,
        changes=changes,
        units=units,
        browse=browse,
        state_dir=state_dir,
        archived=changes,
        log=log,
        create_cap=cap,
        dry_run=dry_run,
    )
    if dry_run:
        would = ", ".join(report.listed)
        log(f"tracker {repo}: backfill would create {len(report.listed)}: {would}")
    return BackfillReport(created=report.created, listed=report.listed)
