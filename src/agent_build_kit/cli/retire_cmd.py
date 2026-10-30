"""`abk retire`: end a unit that has not finished.

Spec: a-started-unit-keeps-its-groups.

Every refusal is decided before the first change, so the command is all-or-nothing up to the
state write; a failure after it (the host down) leaves the unit retired, says what remains and
exits 1.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Callable
from contextlib import ExitStack
from pathlib import Path

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline import retirement
from agent_build_kit.pipeline.lease import Leases, lease_dir
from agent_build_kit.pipeline.shell import git, git_out
from agent_build_kit.pipeline.unit_store import IDLE_NOTE, ClosePending, StoredUnit, UnitStore
from agent_build_kit.pipeline.units import RUNNING, base_of, branch_name
from agent_build_kit.pipeline.workspaces import (
    BranchBusy,
    branch_lock,
    changed_paths,
    remove_worktree,
    unit_tree,
)


def _commits(count: int) -> str:
    return f"{count} commit{'' if count == 1 else 's'} not pushed"


def _unpushed(repo: Path, unit: StoredUnit, units: list[StoredUnit]) -> tuple[str, int | None]:
    """Where the count starts and the commits on the unit's branch after it: the last pushed
    commit, or the base when none was pushed. The count is 0 when the branch is not in the
    checkout, and None when git cannot read it: unknown is not none."""
    since = unit.pushed or base_of(unit, units)
    if not unit.branch or not git_out(repo, "branch", "--list", unit.branch):
        return since, 0
    counted = git(repo, "rev-list", "--count", f"{since}..{unit.branch}", check=False)
    if counted.returncode != 0 or not counted.stdout.strip():
        return since, None
    return since, int(counted.stdout)


def _delete_thread(inst: Installation, unit_id: str) -> None:
    # Late: the graph package imports the pipeline.
    from agent_build_kit.graph.checkpointer import open_unit_graphs

    async def drop() -> None:
        async with open_unit_graphs(inst) as saver:
            await saver.adelete_thread(unit_id)

    asyncio.run(drop())


def retire(
    inst: Installation,
    unit_id: str,
    *,
    say: Callable[..., None],
    reason: str = "",
    delete_branch: bool = False,
    discard_unpushed: bool = False,
    dry_run: bool = False,
) -> int:
    """Retire `unit_id`; every message goes to `say(text, error=...)`. The result is the
    command's exit code: 0 done, 1 refused or partly done, 2 for an unknown unit."""
    # Late: the pipeline module imports this one.
    from agent_build_kit.cli import pipeline as pipe

    store = pipe.store_for(inst)
    units = store.all()
    known = {u.id: u for u in units}
    if unit_id not in known:
        say(
            f"abk retire: no unit {unit_id!r} (known: {', '.join(sorted(known)) or 'none'})",
            error=True,
        )
        return 2
    unit = known[unit_id]
    if discard_unpushed and not delete_branch:
        say(f"{unit_id}: --discard-unpushed means nothing without --delete-branch")
        return 1
    assessment = retirement.assess(unit_id, units)
    if assessment.refusal:
        say(assessment.refusal)
        return 1
    if holder := Leases(lease_dir(inst.local_dir)).holder(unit_id):
        say(f"{unit_id} has a live lease held by {holder}; stop it first")
        return 1
    unowned = [fate for fate in assessment.groups if not fate.carried_by]
    if unowned and not reason:
        for fate in unowned:
            say(
                f"{unit_id}: group {fate.group} of {fate.change} is carried by no unit; "
                "retiring drops that work"
            )
        say("give --reason TEXT to retire it and release those groups to be planned again")
        return 1

    repo = inst.checkouts[unit.repo]
    tree = unit_tree(repo, unit.branch, inst.worktree_root) if unit.branch else None
    if delete_branch and unit.branch:
        if tree is not None and (dirty := changed_paths(tree)):
            say(f"{tree} has uncommitted changes ({', '.join(dirty)}); commit or remove them first")
            return 1
        since, unpushed = _unpushed(repo, unit, units)
        if unpushed is None:
            say(f"{unit_id}: the commits on {unit.branch} since {since} could not be counted")
        elif unpushed:
            say(f"{unit_id}: {_commits(unpushed)}")
        if unpushed != 0 and not discard_unpushed:
            say("--discard-unpushed accepts losing them")
            return 1

    # A `running` unit is idle, as the scheduler counts it, exactly when no live process holds
    # its branch's lock, so taking the lock is that test: a grant means the unit is idle, and
    # `BranchBusy` names the holder. The holders lock the recorded branch or the computed one,
    # so both are taken, in a fixed order. The command's own lock is why the scheduler's
    # function is not called here: it would read that lock as a holder.
    names = {unit.branch} if unit.branch else set()
    if unit.state == RUNNING:
        names.add(branch_name(unit))
    with ExitStack() as held:
        for name in sorted(names):
            try:
                held.enter_context(branch_lock(name, root=inst.locks_dir))
            except BranchBusy as error:
                say(f"{unit_id}: {error}; stop it first")
                return 1
        # What happened between the first read and the lock: a run may have finished, or a
        # lease been taken. Everything that follows is decided from a fresh read, and a unit
        # that changed in a way the decisions above depend on is turned away, nothing changed.
        units = store.all()
        current = next((u for u in units if u.id == unit_id), None)
        if current is None:
            say(f"{unit_id} is gone; run abk retire again")
            return 1
        fresh = retirement.assess(unit_id, units)
        if fresh != assessment or (current.state, current.pr, current.branch, current.pushed) != (
            unit.state,
            unit.pr,
            unit.branch,
            unit.pushed,
        ):
            say(
                f"{unit_id} changed while it was being checked (now {current.state}); "
                "run abk retire again"
            )
            return 1
        if holder := Leases(lease_dir(inst.local_dir)).holder(unit_id):
            say(f"{unit_id} has a live lease held by {holder}; stop it first")
            return 1
        return _retire(
            inst,
            store,
            current,
            fresh,
            say=say,
            reason=reason,
            idle=unit.state == RUNNING,
            branch=(repo, tree) if delete_branch and unit.branch else None,
            dry_run=dry_run,
        )


def _retire(
    inst: Installation,
    store: UnitStore,
    unit: StoredUnit,
    assessment: retirement.Assessment,
    *,
    say: Callable[..., None],
    reason: str,
    idle: bool,
    branch: tuple[Path, Path | None] | None,
    dry_run: bool,
) -> int:
    """Everything after the checks: describe it, and unless `dry_run` do it."""
    # Late: the pipeline module imports this one.
    from agent_build_kit.cli import pipeline as pipe

    would = "would " if dry_run else ""
    say(f"{would}retire {unit.id}: {unit.state} -> retired" + (f" ({reason})" if reason else ""))
    if idle:
        say(f"  {unit.id} {IDLE_NOTE}")
    for fate in assessment.groups:
        where = f"group {fate.group} of {fate.change}"
        if not fate.carried_by:
            say(f"  {where}: released; no unit builds it, the change is planned again")
        elif fate.merged:
            say(f"  {where}: carried by {fate.carried_by} (merged)")
        else:
            say(f"  {where}: carried by {fate.carried_by} (still owning it)")
    for dependent in assessment.dependents:
        say(f"  no longer waiting on it: {dependent.id} ({dependent.state})")
    repo, tree = branch if branch else (None, None)
    pushed = bool(unit.pushed)
    closing = reason or f"{unit.id} was retired."
    if unit.pr is not None:
        say(f"  {would}close pull request #{unit.pr} with the reason")
    if branch and repo is not None:
        if tree is not None and tree.exists():
            say(f"  {would}remove the worktree {tree}")
        say(f"  {would}delete branch {unit.branch}")
        if pushed:
            say(f"  {would}delete remote branch {unit.branch}")
    if dry_run:
        say("  would delete its thread, if it has one")
        return 0

    released = {fate.change for fate in assessment.groups if not fate.carried_by}
    store.retire(unit.id, reason, idle=idle)
    failed = False
    try:
        if pipe.has_thread(inst, unit.id):
            _delete_thread(inst, unit.id)
    except Exception as error:  # noqa: BLE001 - the unit is retired either way
        say(f"{unit.id}: its thread was not deleted — {error}")
        failed = True
    pipe.update_plans(
        inst,
        lambda records: {
            change: None
            for change, record in records.items()
            if change in released or unit.id in record.get("owned", ())
        },
    )
    if unit.pr is not None:
        try:
            pipe.build_close_pr(for_repo=inst.forge_of)(unit, unit.pr, closing)
        except Exception as error:  # noqa: BLE001 - kept for the next pass
            store.set_close_pending(unit.id, ClosePending(pr=unit.pr, reason=closing))
            say(
                f"{unit.id}: pull request #{unit.pr} is not closed yet — {error}; a pass repeats it"
            )
            failed = True
    if branch and repo is not None:
        failed |= not _delete_branch(inst, unit, repo, say=say, pushed=pushed)
    say(f"retired {unit.id}")
    return 1 if failed else 0


def _delete_branch(
    inst: Installation, unit: StoredUnit, repo: Path, *, say: Callable[..., None], pushed: bool
) -> bool:
    """Remove the worktree, delete the local branch and, when it was pushed, the remote one.
    False when a step failed, after saying which."""
    ok = True
    try:
        remove_worktree(repo, unit.branch, root=inst.worktree_root)
        git_out(repo, "branch", "-D", unit.branch)
    except Exception as error:  # noqa: BLE001 - the rest is still tried
        say(f"{unit.id}: branch {unit.branch} was not deleted — {error}")
        ok = False
    if pushed:
        try:
            forge, identity = inst.forge_of(unit.repo)
            forge.delete_remote_branch(identity, unit.branch)
        except Exception as error:  # noqa: BLE001
            say(f"{unit.id}: remote branch {unit.branch} was not deleted — {error}")
            ok = False
    return ok


def cmd_retire(args: argparse.Namespace, inst: Installation) -> int:
    """End a unit that has not finished, release its groups, close its pull request and keep
    its branch unless asked."""

    def say(text: str, *, error: bool = False) -> None:
        print(text, file=sys.stderr if error else sys.stdout)

    return retire(
        inst,
        args.unit,
        say=say,
        reason=args.reason,
        delete_branch=args.delete_branch,
        discard_unpushed=args.discard_unpushed,
        dry_run=args.dry_run,
    )
