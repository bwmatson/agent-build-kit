"""Ending a chat's attachment to a unit: commit what it changed or discard it, and release the
lease in the same operation (docs/architecture.md). The server and `abk attach release`
both call these."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from agent_build_kit.installation import Installation
from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.lease import Leases, lease_dir
from agent_build_kit.pipeline.shell import git_out
from agent_build_kit.pipeline.unit_store import StoredUnit
from agent_build_kit.pipeline.workspaces import (
    BranchBusy,
    changed_paths,
    discard_changes,
    worktree_path,
)

PLANNING = "planning"


class Adopted(Frozen):
    """What ending an attachment by a commit did: the commit, the unit's state, and whether
    the adopted event reached its thread."""

    commit: str
    state: str
    delivered: bool


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


def state_of(inst: Installation, unit: StoredUnit) -> str:
    from agent_build_kit.cli.pipeline import store_for

    return str(store_for(inst).get(unit.id).state)


def deliver(inst: Installation, unit: StoredUnit, commit: str) -> bool:
    """Hand the unit's thread the adopted event for `commit`. False when the branch is busy
    or the delivery failed; a unit with no thread has nothing to be handed."""
    from agent_build_kit.cli.pipeline import resume_thread, store_for

    store = store_for(inst)
    try:
        resumed = resume_thread(
            inst, store.get(unit.id), "adopted", store=store, reason=f"commit {commit[:9]}"
        )
    except BranchBusy:
        return False
    return resumed is None or not resumed.raised


def finish(inst: Installation, unit: StoredUnit, commit: str) -> Adopted:
    """Deliver a commit made and not delivered, then remove the lease that recorded it."""
    delivered = deliver(inst, unit, commit)
    if delivered:
        leases_of(inst).drop(unit.id)
    return Adopted(commit=commit, state=state_of(inst, unit), delivered=delivered)


def adopt(
    inst: Installation,
    unit: StoredUnit,
    message: str,
    *,
    session: str = "",
    fix: Callable[..., str] | None = None,
) -> Adopted:
    """Commit the unit's changes through the repo's hooks, with `fix` (the unit's agent) given
    what they reject; record the commit on the lease, deliver the adopted event and remove the
    lease. Raises `CommitRejected` when the hooks still reject the commit, with the lease and
    the changes kept."""
    from agent_build_kit.pipeline.wiring import build_commit

    tree = worktree_of(inst, unit)
    if tree is None:
        raise ValueError(f"{unit.id} has no worktree")
    build_commit(unit_id=unit.id, fix=fix, adopted_from=session)(message, cwd=tree)
    head = git_out(tree, "rev-parse", "HEAD")
    leases = leases_of(inst)
    if held := leases.attachment(unit.id):
        leases.mark_committed(unit.id, held.holder, head)
    return finish(inst, unit, head)


def commit_planning(
    inst: Installation, unit: StoredUnit, message: str, *, fix: Callable[..., str] | None = None
) -> str:
    """Commit the planning checkout and release its part of the lease; no unit is sent
    anything. Returns the new head."""
    from agent_build_kit.pipeline.wiring import build_commit

    build_commit(fix=fix)(message, cwd=inst.root)
    leases_of(inst).release_checkout(unit.id, PLANNING)
    return git_out(inst.root, "rev-parse", "HEAD")
