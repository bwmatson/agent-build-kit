"""Ending a chat's attachment to a unit: commit what it changed or discard it, and release the
lease in the same operation (docs/architecture.md). The server and `abk attach release`
both call these."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from agent_build_kit.installation import Installation
from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.consequences import Consequence, consequences_of
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


class NothingToCommit(RuntimeError):
    """The tree holds nothing to commit, so no commit was made, marked or delivered."""


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
    the changes kept, and `NothingToCommit` when there was nothing to commit, with the lease
    kept."""
    from agent_build_kit.pipeline.wiring import build_commit

    tree = worktree_of(inst, unit)
    if tree is None:
        raise ValueError(f"{unit.id} has no worktree")
    if not build_commit(unit_id=unit.id, fix=fix, adopted_from=session)(message, cwd=tree):
        raise NothingToCommit("nothing to commit")
    head = git_out(tree, "rev-parse", "HEAD")
    leases = leases_of(inst)
    if held := leases.attachment(unit.id):
        leases.mark_committed(unit.id, held.holder, head)
    return finish(inst, unit, head)


class PlanningCommit(Frozen):
    """A commit of the planning checkout and what it means for the change's started units."""

    commit: str
    consequences: tuple[Consequence, ...]


def planning_gate(inst: Installation, change: str) -> Callable[[Path], str]:
    """The planning checkout's gate, what `abk check` and `abk tags <change>` run. It returns
    what they reject, or nothing."""

    def gate(cwd: Path) -> str:
        from agent_build_kit import openspec
        from agent_build_kit.pipeline.work_graph import check_tags

        rejected = []
        ok, output = openspec.check(cwd)
        if not ok:
            rejected.append(f"abk check failed:\n{output}".strip())
        _, errors = check_tags(change, inst.changes_dir, repos=tuple(inst.repos))
        if errors:
            rejected.append(f"abk tags {change} failed:\n" + "\n".join(errors))
        return "\n\n".join(rejected)

    return gate


def commit_planning(
    inst: Installation, unit: StoredUnit, message: str, *, fix: Callable[..., str] | None = None
) -> PlanningCommit:
    """Commit the planning checkout through the change's gate and release its part of the
    lease; no unit is sent anything or changed. Raises `CommitRejected` when the gate still
    rejects the commit after the agent's fixes, and `NothingToCommit` when the checkout holds
    no change."""
    from agent_build_kit.cli.pipeline import store_for
    from agent_build_kit.pipeline.wiring import build_commit

    before = git_out(inst.root, "rev-parse", "HEAD")
    if not build_commit(fix=fix, gate=planning_gate(inst, unit.change))(message, cwd=inst.root):
        raise NothingToCommit("nothing to commit")
    after = git_out(inst.root, "rev-parse", "HEAD")
    # What the lease still holds is what the checkouts it still covers hold: the planning
    # files are committed now, so they must stop counting.
    leases = leases_of(inst)
    held = leases.attachment(unit.id)
    left = len(changes_of(inst, unit)) if held and "worktree" in held.checkouts else 0
    leases.release_checkout(unit.id, PLANNING, changed=left)
    listed = consequences_of(inst, unit.change, before, after, store=store_for(inst))
    return PlanningCommit(commit=after, consequences=tuple(listed))
