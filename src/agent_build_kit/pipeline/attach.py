"""Ending a chat's attachment to a unit: commit what it changed or discard it, and release the
lease in the same operation (docs/architecture.md). The server and `abk attach release`
both call these."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.lease import Leases, lease_dir
from agent_build_kit.pipeline.unit_store import StoredUnit
from agent_build_kit.pipeline.workspaces import (
    changed_paths,
    commit_changes,
    discard_changes,
    worktree_path,
)


def worktree_of(inst: Installation, unit: StoredUnit) -> Path | None:
    """The unit's worktree, when it exists."""
    if not unit.branch or unit.repo not in inst.checkouts:
        return None
    path = worktree_path(inst.checkouts[unit.repo], unit.branch, inst.worktree_root)
    return path if path.is_dir() else None


def leases_of(inst: Installation) -> Leases:
    return Leases(lease_dir(inst.state_dir))


def changes_of(inst: Installation, unit: StoredUnit) -> tuple[str, ...]:
    tree = worktree_of(inst, unit)
    return changed_paths(tree) if tree is not None else ()


def discard(inst: Installation, unit: StoredUnit) -> None:
    """Restore the unit's worktree to its branch head and release its lease."""
    if (tree := worktree_of(inst, unit)) is not None:
        discard_changes(tree)
    leases_of(inst).drop(unit.id)


def commit(inst: Installation, unit: StoredUnit, message: str) -> str:
    """Commit the unit's changes, release its lease and return the new head."""
    tree = worktree_of(inst, unit)
    if tree is None:
        raise ValueError(f"{unit.id} has no worktree")
    head = commit_changes(tree, message)
    leases_of(inst).drop(unit.id)
    return head
