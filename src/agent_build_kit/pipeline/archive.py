"""Archiving a change once all of its work has landed.

`openspec archive` folds a change's spec deltas into `openspec/specs/`, which
is what keeps those specs describing current behaviour rather than intentions
(docs/architecture.md). It is the only step that rewrites the
planning repo's own record, so three rules apply:

- **Only when every unit has merged.** Archiving earlier publishes behaviour
  that isn't in `main`.
- **In merge order.** Two changes touching the same requirement conflict when
  the second is archived, and the later one has to apply on top of the
  earlier.
- **Never twice.** "All merged" stays true forever, so without a check every
  round would try again and fail noisily.

A failure here is not swallowed. An archive conflict means two changes
disagree about a requirement, which is exactly the kind of thing a person
should look at rather than a pipeline paper over.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

from agent_build_kit import openspec
from agent_build_kit.pipeline.unit_store import StoredUnit
from agent_build_kit.pipeline.units import SATISFIED

# A subprocess.run-like callable, for tests to record the OpenSpec CLI call
# instead of making it.
Runner = Callable[..., subprocess.CompletedProcess]

# States that mean a unit will never merge, and so must not hold its change
# back: "unplanned" is work the plan dropped, which would otherwise strand the
# change permanently; "satisfied" is a unit whose groups landed through a
# predecessor and so never opens a PR of its own to merge.
FINISHED_WITHOUT_MERGING = ("unplanned", SATISFIED)


def is_ready_to_archive(change: str, units: list[StoredUnit]) -> bool:
    """Has every unit of this change landed?"""
    mine = [unit for unit in units if unit.change == change]
    if not mine:
        # Nothing merged is not the same as everything merged; an empty change
        # would otherwise archive itself the moment it appeared.
        return False

    return all(unit.state == "merged" or unit.state in FINISHED_WITHOUT_MERGING for unit in mine)


def _merged_at(change: str, units: list[StoredUnit]) -> str:
    """When this change's last unit merged, for ordering."""
    stamps = [
        entry.get("at", "")
        for unit in units
        if unit.change == change
        for entry in unit.history
        if entry.get("state") == "merged"
    ]
    return max(stamps) if stamps else ""


def _already_archived(change: str, planning_repo: Path, specs_dir: str = "openspec") -> bool:
    archive = planning_repo / specs_dir / "changes" / "archive"
    if not archive.exists():
        return False
    return any(entry.name.endswith(f"-{change}") for entry in archive.iterdir())


def archive_ready_changes(
    units: list[StoredUnit],
    *,
    planning_repo: Path,
    run: Runner | None = None,
    may_archive: Callable[[str], bool] = lambda change: True,
    specs_dir: str = "openspec",
) -> list[str]:
    """Archive every change whose units have all merged, oldest merge first —
    and that `may_archive` lets through: the tick passes whether the change
    has been deployed and passed its live tests (verify.py).

    Returns the changes archived, so the caller can commit them and say so in
    the run log.
    """
    ready = {
        unit.change
        for unit in units
        if is_ready_to_archive(unit.change, units)
        and not _already_archived(unit.change, planning_repo, specs_dir)
        and may_archive(unit.change)
    }

    archived: list[str] = []
    for change in sorted(ready, key=lambda name: _merged_at(name, units)):
        # A conflict raises rather than being auto-resolved.
        openspec.archive(change, cwd=planning_repo, run=run)
        archived.append(change)

    return archived
