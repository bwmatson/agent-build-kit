"""What the pipeline does when GitHub tells it something changed.

`pr_poller` watches PRs and names what happened; this decides what to do about
it. Without these handlers nothing moves past `open` — a merged PR leaves its
unit sitting there, and the branches above it stay stacked on one that no
longer needs to exist.

**Merging the bottom of a stack is the event that matters.** Every branch
above it is still based on the merged branch, so until they are moved, each
child's PR shows its parent's work as part of its own diff. The move is a
rebase onto the child's next still-open parent — `main` only when there isn't
one, since sending a three-deep stack's top straight to `main` would drop the
middle unit's work out from under it.

Two rules hold throughout:

- **Nothing cascades.** Closing a PR is a decision about one unit; propagating
  it would discard branches nobody asked to drop.
- **One failure is one unit's failure.** A conflicted restack is left for a
  human, and the rest of the stack still moves — otherwise a single conflict
  freezes everything above it.

And one about timing: **a unit being built is not touched.** A pass polls
between builds, so an event can arrive for a unit whose build is still
running — a review on a unit being reworked, a merge under a child still
building. Each handler takes the unit's branch lock before acting, as the
build does; when a build holds it, the handler does nothing and reports the
event deferred, and the poller keeps it to report again on a later poll.
Acting mid-build would rebase the tree the agent is writing to, or be
overwritten by the state the build records when it ends.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from contextlib import AbstractContextManager, nullcontext
from functools import partial
from pathlib import Path

from agent_build_kit import forges, profiles
from agent_build_kit.forges import Forge, PullRequest, RepoId, ReviewNote
from agent_build_kit.forges.base import cancelled_names, failing_names
from agent_build_kit.model import Frozen
from agent_build_kit.pipeline import spans
from agent_build_kit.pipeline.pr_poller import FAILING_CHECKS_REASON  # noqa: F401 — re-exported
from agent_build_kit.pipeline.pr_replies import MARKER, record_posts
from agent_build_kit.pipeline.restack import (
    Moved,
    RestackConflict,
    adopt_host_head,
    blast_radius_note,
    push_with_lease,
    remote_head,
    resolved_move,
)
from agent_build_kit.pipeline.restack import diff_id as restack_diff_id
from agent_build_kit.pipeline.shell import git
from agent_build_kit.pipeline.stack_runner import PREDECESSOR_NOTE, Comment
from agent_build_kit.pipeline.ui_review import attach_hunks
from agent_build_kit.pipeline.unit_store import (
    Cause,
    HeldBy,
    ReworkKind,
    StoredUnit,
    UnitStore,
    feedback_source_of,
)
from agent_build_kit.pipeline.units import (
    CLOSED,
    HELD,
    IN_FLIGHT,
    IN_REVIEW,
    MERGED,
    PLANNED,
    RUNNING,
    SATISFIED,
    base_of,
    branch_name,
    depth_of,
    local_ref,
    through_satisfied,
)
from agent_build_kit.pipeline.wiring import build_tier1
from agent_build_kit.pipeline.workspaces import BranchBusy, branch_lock, worktree_path
from agent_build_kit.pipeline.workspaces import remove_worktree as drop_worktree
from agent_build_kit.runtimes.base import AgentInterrupted, AgentRateLimited

Log = Callable[[str], None]
Restack = Callable[..., None]
# Holds a unit's branch for the length of a handler, or raises `BranchBusy`
# because a build holds it. See the module docstring.
Claim = Callable[[StoredUnit], AbstractContextManager[object]]
# Delivers an event (its kind, reason, feedback and whether the feedback is a
# person's words, which only a rework has) to the unit's thread on the
# graph engine, which leaves the thread positioned at the node the event routes
# to for the tick to run: True when it did, False when the unit has no thread
# and the handler does what it always did, `BranchBusy` when the event cannot be
# delivered now, because the branch is held or the thread has a node to run. It
# is called without the claim, as the delivery takes the branch's lock itself.
#
# A rework hands `feedback` as a zero-argument callable returning `(words,
# from_person, comment_ids)` rather than the words: what review said costs requests, and is
# worth them only once the delivery holds the lock and the thread is waiting. The ids are
# those of the comments the words were built from, which are the only ones the agent is given.
Resume = Callable[..., bool]
Feedback = Callable[[], tuple[str, bool, tuple[str, ...]]]


def _no_thread(
    unit: StoredUnit,
    kind: str,
    reason: str,
    feedback: str | Feedback,
    *,
    from_person: bool = False,
    rework: ReworkKind | None = None,
) -> bool:
    return False


# What a hold for depth says, so a later merge can find what it held and which
# branch it still sits on.
DEPTH_HOLD = "restack onto {new_base} skipped: depth {depth} is beyond the rebase cap {cap}"
DEPTH_HOLD_BASE = " (still on {old_base})"
# What the label handler writes as a hold's note when the reviewer's hold has
# no reason of its own. Prose for people: nothing reads it.
HELD_BY_A_REVIEWER = "held by a reviewer"


def held_for_depth(unit: StoredUnit) -> bool:
    """Held for the stack depth cap, which a later merge may free: by the holder
    the record keeps. A record from before it was kept is not read from its note."""
    return unit.state == HELD and unit.held_by == HeldBy.DEPTH


def held_for_its_own_reason(unit: StoredUnit) -> bool:
    """Held for a reason the hold label did not make and its removal must not undo:
    the review loop, the toolchain, a cause not recorded. A depth hold is not one,
    since a merge frees it, so the label takes it over; and a unit the label
    already holds is not held for another reason."""
    return unit.state == HELD and not unit.held_by_the_label and not held_for_depth(unit)


def held_cause(unit: StoredUnit) -> str:
    return unit.held_by or "an unrecorded cause"


def takeover_note(unit: StoredUnit, reason: str = "") -> str:
    """The note the label's hold on `unit` is recorded with. A depth hold keeps its
    own, for a person reading it; the branch it is still on is the `held_base` field."""
    if held_for_depth(unit):
        return unit.note
    return reason or HELD_BY_A_REVIEWER


def restore_depth_hold(store: UnitStore, unit: StoredUnit) -> bool:
    """Give a unit the label took a depth hold from back to that hold, as the
    `held_base` it kept says. False when the label's hold was not over one."""
    if not unit.held_base:
        return False
    store.set_state(
        unit.id,
        HELD,
        note=unit.note,
        held_by=HeldBy.DEPTH,
        cause=Cause.DEPTH,
        held_base=unit.held_base,
    )
    return True


def _unclaimed(unit: StoredUnit) -> AbstractContextManager[object]:
    return nullcontext()


def build_claim(locks: Path) -> Claim:
    """The same branch lock `build_unit` holds while a unit builds, by the same name."""

    def claim(unit: StoredUnit) -> AbstractContextManager[object]:
        return branch_lock(branch_name(unit), root=locks)

    return claim


def _deferred(event: str, unit: StoredUnit, error: BranchBusy, log: Log) -> bool:
    log(f"{event}: {unit.id} is being built ({error}) — left for a later poll")
    return False


def _find(store: UnitStore, repo: str, pr: int) -> StoredUnit | None:
    """The unit a pull request belongs to: the one in `repo` with that number.

    Both, never the number alone. Numbers are per repo, so two repos in one
    workspace reach the same one, and an event matched on the number is
    applied to whichever unit comes first in the store — a merge recorded
    against another repo's unit, while the one that merged waits in review.
    """
    for unit in store.all():
        if unit.repo == repo and unit.pr == pr:
            return unit
    return None


def on_merged(
    pr: int,
    *,
    repo: str,
    store: UnitStore,
    restack: Restack,
    remove_worktree: Callable[..., None] | None = None,
    delete_branch: Callable[..., None] | None = None,
    claim: Claim = _unclaimed,
    retarget: Callable[[StoredUnit, str], None] | None = None,
    rebase_cap: int | None = None,
    resume: Resume = _no_thread,
    log: Log = print,
) -> bool:
    """Record the merge, move what was stacked on it, then clean up after it.

    False when the merged unit is itself being built — a rework someone
    merged over — so the poller reports the merge again once it has finished.
    """
    merged = _find(store, repo, pr)
    if merged is None:
        # Someone else's PR on a spec/ branch, a unit dropped from the store,
        # or a number only another repo's unit has. Restacking against a unit
        # we don't know moves the wrong branch, so do nothing at all.
        log(f"merged #{pr}: no unit recorded for it in {repo}, ignoring")
        return True

    try:
        # First: a thread mid-node defers the event before anything is recorded.
        resume(merged, "merged", "", "")
        with claim(merged):
            _record_merge(
                merged,
                store=store,
                restack=restack,
                remove_worktree=remove_worktree or (lambda repo, branch: None),
                delete_branch=delete_branch or (lambda repo, branch: None),
                claim=claim,
                retarget=retarget or (lambda unit, base: None),
                rebase_cap=rebase_cap,
                resume=resume,
                log=log,
            )
    except BranchBusy as error:
        return _deferred(f"merged #{pr}", merged, error, log)
    return True


def release_children(
    leaving: StoredUnit,
    *,
    store: UnitStore,
    restack: Restack,
    remove_worktree: Callable[..., None] | None = None,
    delete_branch: Callable[..., None] | None = None,
    claim: Claim = _unclaimed,
    retarget: Callable[[StoredUnit, str], None],
    rebase_cap: int | None = None,
    resume: Resume = _no_thread,
    settled: Callable[[StoredUnit, str], bool] = lambda child, base: False,
    log: Log = print,
) -> list[str]:
    """Move what is stacked on a unit that has left the stack — merged or
    satisfied, already recorded as such in the store — onto its new base, then,
    when given the means, remove the unit's worktree and branch once nothing
    builds on it.

    `settled` says a child is already where this would put it, so a second
    release of the same unit moves and tells nothing.

    Returns what it could not move, one line each — the child, the branch it is
    still on and why — for the caller to record on the unit that left.
    """
    # Re-read: the children's new bases are worked out from the graph with the
    # merge already applied, which is what makes a leaving parent drop out of
    # `base_of` instead of still being offered as a base.
    graph = store.all()
    old_base = branch_name(leaving)
    building_on_it: list[str] = []
    held_for_depth: list[str] = []
    not_moved: list[str] = []
    failures: list[str] = []

    def unmoved(child: StoredUnit, why: object) -> None:
        if child.id not in not_moved:
            not_moved.append(child.id)
        failures.append(f"{child.id} not moved off {old_base} — {why}")

    def retargeted(child: StoredUnit, new_base: str) -> bool:
        try:
            retarget(child, new_base)
        except Exception as error:  # noqa: BLE001
            log(f"{child.id}: PR not retargeted to {new_base} — {error}")
            unmoved(child, error)
            return False
        return True

    for child in _children_of(leaving, graph):
        new_base = base_of(child, graph)
        if new_base == old_base:
            continue  # Nothing to do: it is not what this child sat on.
        if settled(child, new_base):
            continue  # Moved by an earlier release.

        depth = depth_of(child, graph)
        try:
            # A child with a thread is told its base moved, and its thread
            # moves the branch when the tick runs it; without the claim, as the
            # delivery takes the branch's lock itself. One held, by a person or
            # for depth, is not moved: only a thread waiting in review is told.
            if child.state == IN_REVIEW and (rebase_cap is None or depth <= rebase_cap):
                try:
                    told = resume(child, "base_moved", new_base, "")
                except BranchBusy:
                    # The merge is consumed either way. Nothing re-tells the
                    # thread: it moves onto the new base on its next rework or
                    # conflict, so say so, and keep the old branch for it.
                    log(
                        f"{child.id}: its thread was not told the base is now {new_base}, "
                        "the branch is busy; it moves on its next rework or conflict"
                    )
                    building_on_it.append(child.id)
                    retargeted(child, new_base)
                    continue
                if told:
                    log(f"{child.id}: its thread is told the base is now {new_base}")
                    # At once, as every other path here: a PR left on a branch merged
                    # away may be closed, and the thread only retargets when it runs.
                    retargeted(child, new_base)
                    continue
            with claim(child):
                if rebase_cap is not None and depth > rebase_cap:
                    _hold_for_depth(
                        store, child, new_base, old_base, depth, rebase_cap, retargeted, log
                    )
                    held_for_depth.append(child.id)
                    continue
                restack(
                    branch=branch_name(child),
                    old_base=old_base,
                    new_base=new_base,
                    child=child,
                    parent=leaving,
                )
        except BranchBusy:
            # Its build is running in the tree a restack would rebase. The
            # merge stands regardless, so the build stops at its next step on
            # seeing its base has moved, and its resume moves the branch (see
            # `wiring.build_base_moved`). Only the PR moves now, which touches
            # no tree: one left on a deleted base may be closed.
            log(f"{child.id}: being built — its build moves it onto {new_base} when it resumes")
            building_on_it.append(child.id)
            retargeted(child, new_base)
            continue
        except Exception as error:  # noqa: BLE001
            # Left where it is, still open, still based on the old branch. A
            # human resolves it; the rest of the stack is not held up for it.
            log(f"{child.id}: restack onto {new_base} failed — {type(error).__name__}: {error}")
            unmoved(child, f"{type(error).__name__}: {error}")
            continue

        log(f"{child.id}: restacked onto {new_base}")

    if rebase_cap is not None:
        still_held = _reconsider_held(
            leaving, store=store, restack=restack, claim=claim, rebase_cap=rebase_cap, log=log
        )
        held_for_depth += [held for held in still_held if held not in held_for_depth]

    if remove_worktree and delete_branch:
        _remove_leaving(
            leaving,
            graph=graph,
            claim=claim,
            remove_worktree=remove_worktree,
            delete_branch=delete_branch,
            building_on_it=building_on_it,
            held_for_depth=held_for_depth,
            not_moved=not_moved,
            log=log,
        )
    return failures


def remove_satisfied(
    leaving: StoredUnit,
    *,
    store: UnitStore,
    claim: Claim = _unclaimed,
    remove_worktree: Callable[..., None],
    delete_branch: Callable[..., None],
    on_new_base: Callable[[StoredUnit], bool],
    log: Log = print,
) -> None:
    """Remove a satisfied unit's worktree and branch, once the run that found it
    satisfied has left its tree, by the rules a merged unit's removal follows.

    The release has already moved its dependents, so what keeps the branch is
    read from the store and the host rather than remembered from that pass: a
    dependent held for depth, one whose pull request is not yet on its new
    base, or one that is being built.
    """
    graph = store.all()
    old_base = branch_name(leaving)
    children = {child.id for child in _children_of(leaving, graph)}
    held_for_depth: list[str] = []
    not_moved: list[str] = []
    for dependent in _dependents_of(leaving, graph):
        if dependent.state == HELD and dependent.held_base == old_base:
            held_for_depth.append(dependent.id)
        elif dependent.id in children and not on_new_base(dependent):
            not_moved.append(dependent.id)
    _remove_leaving(
        leaving,
        graph=graph,
        claim=claim,
        remove_worktree=remove_worktree,
        delete_branch=delete_branch,
        building_on_it=[],
        held_for_depth=held_for_depth,
        not_moved=not_moved,
        log=log,
    )


def _remove_leaving(
    leaving: StoredUnit,
    *,
    graph: list[StoredUnit],
    claim: Claim,
    remove_worktree: Callable[..., None],
    delete_branch: Callable[..., None],
    building_on_it: list[str],
    held_for_depth: list[str],
    not_moved: list[str],
    log: Log,
) -> None:
    old_base = branch_name(leaving)

    # Last, and only the leaving unit's own: a child still has an open PR and
    # may yet be restacked or reworked in its tree. Nothing else ever removes
    # one, so without this each unit leaves a full checkout behind for good.
    try:
        remove_worktree(leaving.repo, old_base)
    except Exception as error:  # noqa: BLE001
        # `remove_worktree` refuses a dirty tree on purpose — uncommitted work
        # there may be the only copy. The merge already happened either way,
        # and the branch stays too: deleting it would strand that work on a
        # checkout with no ref pointing at it.
        log(f"{leaving.id}: worktree and branch left in place — {error}")
        return

    # A build holds its lock and fixes its base ref while its unit still reads
    # `planned`, so the state alone misses one that is just starting. The lock
    # does not: MERGED is already written, so a build that takes it after this
    # probe sees the trunk from `base_of`, and one holding it now is exactly
    # one that may have taken this branch. It is not moved here — its own
    # resume restacks it.
    for dependent in _dependents_of(leaving, graph):
        if dependent.id in building_on_it:
            continue
        try:
            # The probe holds the lock for an instant. A build starting this
            # unit in that instant gets `BranchBusy` and skips it. The pass
            # that handed it out counts it as started and does not retry it;
            # it is still `planned`, so the next pass takes it up.
            with claim(dependent):
                pass
        except BranchBusy:
            building_on_it.append(dependent.id)

    if held_for_depth:
        # Still based on this branch, and not moved: deleting it strands them.
        log(f"{leaving.id}: branch {old_base} kept — {', '.join(held_for_depth)} held for depth")
        return

    if not_moved:
        # Still based on this branch, and left for a person: deleting it
        # strands them.
        log(f"{leaving.id}: branch {old_base} kept — {', '.join(not_moved)} not moved off it")
        return

    if building_on_it:
        # A running build fixed its base ref when it started, and for a stacked
        # child that ref is this local branch. Deleted under it, the build's
        # diffs and commit counts come back empty, and it fails as "produced
        # no commits" before its next step can hold it. A leftover local
        # branch is harmless; the child's resume moves it off by name.
        log(f"{leaving.id}: branch {old_base} kept — {', '.join(building_on_it)} building on it")
        return

    try:
        # Only now: a branch checked out in a worktree cannot be deleted, so
        # the order is a requirement rather than a preference.
        delete_branch(leaving.repo, old_base)
    except Exception as error:  # noqa: BLE001
        log(f"{leaving.id}: branch {old_base} left in place — {error}")


def _record_merge(
    merged: StoredUnit,
    *,
    store: UnitStore,
    restack: Restack,
    remove_worktree: Callable[..., None],
    delete_branch: Callable[..., None],
    claim: Claim,
    retarget: Callable[[StoredUnit, str], None],
    rebase_cap: int | None,
    resume: Resume,
    log: Log,
) -> None:
    store.set_state(merged.id, MERGED, cause=Cause.MERGED)
    log(f"merged #{merged.pr}: {merged.id}")

    release_children(
        merged,
        store=store,
        restack=restack,
        remove_worktree=remove_worktree,
        delete_branch=delete_branch,
        claim=claim,
        retarget=retarget,
        rebase_cap=rebase_cap,
        resume=resume,
        log=log,
    )


def _hold_for_depth(
    store: UnitStore,
    child: StoredUnit,
    new_base: str,
    old_base: str,
    depth: int,
    cap: int,
    retarget: Callable[[StoredUnit, str], bool],
    log: Log,
) -> None:
    note = DEPTH_HOLD.format(new_base=new_base, depth=depth, cap=cap)
    store.set_state(
        child.id,
        HELD,
        note=note + DEPTH_HOLD_BASE.format(old_base=old_base),
        held_by=HeldBy.DEPTH,
        cause=Cause.DEPTH,
        held_base=old_base,
    )
    log(f"{child.id}: held — {note}")
    # Only the PR moves, as for a child being built: it touches no tree, and
    # one left on the merged branch may be closed by the host, which would put
    # the unit out of reach of a later reconsideration.
    retarget(child, new_base)


def _reconsider_held(
    merged: StoredUnit,
    *,
    store: UnitStore,
    restack: Restack,
    claim: Claim,
    rebase_cap: int,
    log: Log,
) -> list[str]:
    """Restack what an earlier merge held for depth and this one brought within
    the cap, in the merged unit's repo. Returns those still held on the merged
    unit's own branch, which is the one its caller must keep.

    Depth only falls, so a merge anywhere below a held unit can free it without
    anyone touching it.
    """
    still_held: list[str] = []
    graph = store.all()
    for unit in graph:
        if unit.repo != merged.repo or unit.state != HELD or not unit.branch:
            continue
        old_base = unit.held_base
        if not old_base:
            continue  # Held by a person or the toolchain, not for depth.
        if unit.held_by_the_label:
            # A reviewer has it, over a depth hold: not restacked while the label
            # is on, and still on its old base.
            if old_base == branch_name(merged):
                still_held.append(unit.id)
            continue
        if reconsider_depth_hold(
            unit,
            old_base,
            graph,
            store=store,
            restack=restack,
            claim=claim,
            rebase_cap=rebase_cap,
            log=log,
        ) and old_base == branch_name(merged):
            still_held.append(unit.id)
    return still_held


def reconsider_depth_hold(
    unit: StoredUnit,
    old_base: str,
    graph: list[StoredUnit],
    *,
    store: UnitStore,
    restack: Restack,
    claim: Claim,
    rebase_cap: int,
    log: Log,
) -> bool:
    """Restack a unit held for depth if its depth is now within the cap, from the
    branch it is still on. True when it is still held, on that branch."""
    depth = depth_of(unit, graph)
    new_base = base_of(unit, graph)
    parent = next((u for u in graph if branch_name(u) == old_base), None)
    if depth > rebase_cap or parent is None:
        return True
    try:
        with claim(unit):
            store.set_state(
                unit.id, IN_REVIEW, note=f"depth {depth} is within the cap", cause=Cause.RELEASED
            )
            restack(
                branch=branch_name(unit),
                old_base=old_base,
                new_base=new_base,
                child=unit,
                parent=parent,
            )
    except BranchBusy:
        # The claim failed before anything was written: it is still held,
        # its record as it was, and the next merge tries again.
        return True
    except Exception as error:  # noqa: BLE001
        # Left in review on its old base, as a failed restack is for a
        # child in the merge itself.
        log(f"{unit.id}: restack onto {new_base} failed — {type(error).__name__}: {error}")
        return False
    log(f"{unit.id}: restacked onto {new_base}")
    return False


def _children_of(parent: StoredUnit, graph: list[StoredUnit]) -> list[StoredUnit]:
    """The still-open units stacked on `parent`, in the same repo.

    Not only its direct dependents: a unit whose real dependency is `parent`
    but whose own `depends_on` names a satisfied unit in between is stacked on
    `parent` all the same, since the satisfied unit between them added no
    commits of its own — `through_satisfied` looks past it the same way
    `base_of` does, so a grandchild through one is restacked (or held) here
    exactly as a direct child would be. A unit that names `parent` itself is
    stacked on it even when `parent` is satisfied, for a unit built on its
    branch before it was.

    A cross-repo dependent is never stacked on it — stacks can't span repos —
    so it has nothing to move; `ready_units` makes it wait for the merge
    instead.
    """
    return [
        unit
        for unit in graph
        if parent.id in (*unit.depends_on, *through_satisfied(unit, graph))
        and unit.repo == parent.repo
        and unit.state in IN_FLIGHT
        and unit.branch
    ]


def _dependents_of(parent: StoredUnit, graph: list[StoredUnit]) -> list[StoredUnit]:
    """Every same-repo unit on `parent` that may yet build, whatever its state.

    Wider than `_children_of`: a build may already have taken `parent`'s
    branch as its base before it has a branch or reads `running`. Reaches
    through a satisfied intermediate unit the same way `_children_of` does.
    """
    return [
        unit
        for unit in graph
        if parent.id in (*unit.depends_on, *through_satisfied(unit, graph))
        and unit.repo == parent.repo
        and unit.state not in (MERGED, CLOSED)
    ]


def build_delete_branch(repos: dict[str, Path]) -> Callable[..., None]:
    """Delete a merged unit's local branch.

    Forced, because it has to be: GitHub squash-merges, so the branch is not
    an ancestor of main and `git branch -d` refuses it every time. That force
    is only defensible here — the poller saw GitHub report the PR merged, so
    the work is in main under a different SHA. The same flag in
    `remove_worktree`, which knows nothing about merge status, would destroy
    unmerged work, and `on_closed` deliberately does not do this at all.

    The remote branch needs no attention: GitHub deletes the head branch on
    merge, which the pilot confirmed — both remotes were already clean while
    both local branches remained.
    """

    def delete(repo: str, branch: str) -> None:
        result = git(repos[repo], "branch", "-D", branch, check=False)
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or f"could not delete {branch}")

    return delete


class Review(Frozen):
    """The reviewer's words, and the id of every note they were read from, outdated or not."""

    lines: list[str] = []
    ids: tuple[str, ...] = ()


def review_lines(notes: list[ReviewNote]) -> list[str]:
    """The reviewer's words, skipping anything the host says is stale.

    A note goes stale when the code it sat on changes — GitHub reports
    `line: null`, Azure DevOps resolves the thread — and the forge reports
    either as `live=False`. After a rework that is precisely the note the
    rework addressed, so replaying it tells the agent to redo work it has
    already done, and every later round would carry every earlier note with it.

    A submitted review's own body is not anchored to a line, so it has nothing
    to go stale against and is always included.

    The pipeline's own replies (marked with `pr_replies.MARKER`) are left out:
    they answer the review, and read back as review they would have the next
    rework respond to itself. Each inline note carries its id, which is how the
    rework says which thread each of its replies belongs in.
    """
    out = []
    for note in notes:
        body = note.body.strip()
        if not body or MARKER in body:
            continue
        if (note.line is None and not note.path) or note.live:
            out.append(note_words(note))
    return out


def note_words(note: ReviewNote) -> str:
    """One note as the rework reads it: the tagged `path:line — body` line, or the bare body
    for a note anchored nowhere. The tag is how a reply finds its thread, so every
    place that hands a note to the agent writes it here."""
    body = note.body.strip()
    if note.line is None and not note.path:
        return body
    tag = f"[comment {note.id}] " if note.id else ""
    words = f"{tag}{note.path or '?'}:{note.line} — {body}"
    return f"{words}\n{note.hunk}" if note.hunk else words


def _notes_of(
    forge: Forge,
    repo_id: RepoId,
    repo: str,
    pr: int,
    extra_notes: Callable[[str, int], list[ReviewNote]] | None,
    patch_of: Callable[[str, int], str] | None,
) -> list[ReviewNote]:
    """The host's notes on a PR and `extra_notes` (a review made elsewhere), each carrying the
    hunk of the unit's `patch_of` that holds its line."""
    notes = [*forge.review_notes(repo_id, pr), *(extra_notes(repo, pr) if extra_notes else [])]
    patch = patch_of(repo, pr) if patch_of else ""
    return attach_hunks(notes, patch) if patch else notes


def build_fetch_review(
    *,
    for_repo: Callable[[str], tuple[Forge, RepoId]] | None = None,
    extra_notes: Callable[[str, int], list[ReviewNote]] | None = None,
    patch_of: Callable[[str, int], str] | None = None,
) -> Callable[..., Review]:
    """The reviewer's words on a PR, asked of whichever host it lives on.

    Fetched only when a rework is already being dispatched: asking during the
    poll itself would cost one request per open PR per tick. `extra_notes` adds a review
    made off the host (the web UI's), and `patch_of` is the unit's own diff, from which
    every note takes the hunk holding its line.
    """
    for_repo = for_repo or forges.for_repo

    def fetch(repo: str, pr: int) -> Review:
        forge, repo_id = for_repo(repo)
        notes = _notes_of(forge, repo_id, repo, pr, extra_notes, patch_of)
        return Review(lines=review_lines(notes), ids=tuple(n.id for n in notes))

    return fetch


def build_fetch_comments(
    *,
    for_repo: Callable[[str], tuple[Forge, RepoId]] | None = None,
    own: Callable[[str, int], set[str]] = lambda repo, pr: set(),
    extra_notes: Callable[[str, int], list[ReviewNote]] | None = None,
    patch_of: Callable[[str, int], str] | None = None,
) -> Callable[[str, int, str], tuple[Comment, ...]]:
    """Every comment on a PR now, by id, for a rework to tell what is new.

    Liveness is not consulted: an outdated note is still the person's. `own` names
    the ids the pipeline posted (`pr_replies.own_posts`); a body carrying
    `pr_replies.MARKER` is the pipeline's too. The PR is looked up by its branch: a host
    may do work for every PR a listing returns. `extra_notes` and `patch_of` are as in
    `build_fetch_review`: a comment made off the host is one a rework can be given too."""
    for_repo = for_repo or forges.for_repo

    def fetch(repo: str, pr: int, branch: str) -> tuple[Comment, ...]:
        forge, repo_id = for_repo(repo)
        mine = own(repo, pr)
        found: dict[str, Comment] = {}
        for note in _notes_of(forge, repo_id, repo, pr, extra_notes, patch_of):
            found[note.id] = Comment(
                id=note.id,
                words=note_words(note) if note.body.strip() else "",
                own=note.id in mine or MARKER in note.body,
            )
        pull = next(
            (p for p in forge.list_prs(repo_id, head_prefix=branch) if p.number == pr), None
        )
        if pull is not None:
            # The host lists comments before reviews, so the bodies line up with the first ids.
            bodies = dict(zip(pull.conversation, pull.comment_bodies, strict=False))
            for comment_id in pull.conversation:
                if comment_id not in found:
                    body = bodies.get(comment_id, "")
                    found[comment_id] = Comment(
                        id=comment_id, words=body, own=comment_id in mine or MARKER in body
                    )
        return tuple(found.values())

    return fetch


def build_fetch_check_logs(
    *, for_repo: Callable[[str], tuple[Forge, RepoId]] | None = None
) -> Callable[..., str]:
    """The failed CI jobs' logs for a PR, for the rework that fixes them.

    The poller already sends a unit back when a check starts failing, but the
    rework used to get only "failing checks: <name>" — and when the failure is
    a test tier 1 never ran, nothing local can say why. Which logs those are,
    and how to reach them, is the forge's business.
    """
    for_repo = for_repo or forges.for_repo

    def fetch(repo: str, pull: PullRequest | None) -> str:
        if pull is None:
            return ""
        forge, repo_id = for_repo(repo)
        text = forge.failed_check_logs(repo_id, pull)
        if not failing_names(pull.checks):
            return text
        # Whatever the host could say, a rework is also told to run what CI
        # runs. A host may have no log to give (GitHub for a run still going,
        # Azure DevOps always: it reports a status and a link), and a log, when
        # there is one, is the end of a failed step, not a reproduction.
        return "\n\n".join(part for part in (text, _reproduce_note(repo)) if part)

    return fetch


def build_rerun_checks(
    *, for_repo: Callable[[str], tuple[Forge, RepoId]] | None = None
) -> Callable[..., None]:
    """Ask a PR's host to run its cancelled checks again."""
    for_repo = for_repo or forges.for_repo

    def rerun(repo: str, pull: PullRequest) -> None:
        forge, repo_id = for_repo(repo)
        forge.rerun_checks(repo_id, pull)

    return rerun


def _reproduce_note(repo: str) -> str:
    """How to see locally what CI saw, from the repo's own toolchain profile.

    Said here, not by each forge: the command is the toolchain's, not the
    host's, and every host's rework needs it.
    """
    from agent_build_kit.config import active

    entry = active().repos.get(repo)
    if entry is None:
        return ""
    lint = " ".join(profiles.get(entry.profile).lint_command_all_files())
    return (
        "CI runs the repository's own checks over the whole repo. Before you change "
        f"anything, run them here to see what it saw: `{lint}`, then the tests. Fix what "
        "they report; the push is judged by that same run."
    )


def build_remove_worktree(repos: dict[str, Path], *, root: Path) -> Callable[..., None]:
    """Drop a finished unit's worktree, keeping its branch and any dirty work.

    `workspaces.remove_worktree` does not force: a tree with uncommitted
    changes is left for a human, because what is in it may be the only copy.
    """

    def remove(repo: str, branch: str) -> None:
        drop_worktree(repos[repo], branch, root=root)

    return remove


def on_closed(
    pr: int,
    *,
    repo: str,
    store: UnitStore,
    claim: Claim = _unclaimed,
    resume: Resume = _no_thread,
    log: Log = print,
) -> bool:
    """Record that a PR was closed without merging.

    Deliberately not propagated to whatever was stacked on it: closing is a
    decision about one unit, and the branches above it hold work that nobody
    asked to drop.

    A satisfied unit is left alone. Its own close — posted, then closed, by
    `wiring.build_close_pr` once its work turned up already implemented
    elsewhere — is this same OPEN→CLOSED transition, and the poller cannot
    tell its close from a human's. Recording it here would turn SATISFIED into
    CLOSED, which blocks archiving, leaves dependents waiting forever (CLOSED
    is not in `REVIEWED`) and stops `through_satisfied` looking through it.
    """
    unit = _find(store, repo, pr)
    if unit is None:
        log(f"closed #{pr}: no unit recorded for it in {repo}, ignoring")
        return True

    try:
        if store.get(unit.id).state == SATISFIED:
            log(f"closed #{pr}: {unit.id} is satisfied — its own close, leaving it as it is")
            return True
        resume(unit, "closed", "", "")
        with claim(unit):
            # Re-read under the lock, as `on_rework` does: a build that has
            # just ended may have moved it.
            if store.get(unit.id).state == SATISFIED:
                log(f"closed #{pr}: {unit.id} is satisfied — its own close, leaving it as it is")
                return True
            store.set_state(unit.id, CLOSED, cause=Cause.CLOSED)
    except BranchBusy as error:
        return _deferred(f"closed #{pr}", unit, error, log)
    log(f"closed #{pr}: {unit.id} — anything stacked on it is left as it stands")
    return True


def on_hold(
    pr: int,
    *,
    repo: str,
    store: UnitStore,
    claim: Claim = _unclaimed,
    resume: Resume = _no_thread,
    log: Log = print,
) -> bool:
    """A reviewer has taken the unit over. Nothing automatic touches it again.

    A unit held for depth is taken over too, since a merge would free it with the
    label still on; one the review loop or the toolchain holds keeps its cause,
    because nothing automatic frees those.

    A satisfied unit is left as it is — see `on_closed` for why its own
    OPEN→CLOSED is not the only transition that can arrive after it is
    already done.
    """
    unit = _find(store, repo, pr)
    if unit is None:
        log(f"hold #{pr}: no unit recorded for it in {repo}, ignoring")
        return True

    try:
        if store.get(unit.id).state == SATISFIED:
            log(f"hold #{pr}: {unit.id} is satisfied, leaving it as it is")
            return True
        if resume(unit, "hold", "", ""):
            current = store.get(unit.id)
            if held_for_its_own_reason(current):
                log(
                    f"hold #{pr}: {unit.id} is already held by {held_cause(current)}, "
                    "leaving it as it is"
                )
            else:
                log(f"hold #{pr}: {unit.id} is held, the pipeline will not touch it")
            return True
        with claim(unit):
            if store.get(unit.id).state == SATISFIED:
                log(f"hold #{pr}: {unit.id} is satisfied, leaving it as it is")
                return True
            current = store.get(unit.id)
            if held_for_its_own_reason(current):
                log(
                    f"hold #{pr}: {unit.id} is already held by {held_cause(current)}, "
                    "leaving it as it is"
                )
                return True
            if not current.held_by_the_label:
                store.set_state(
                    unit.id,
                    HELD,
                    note=takeover_note(current),
                    held_by=HeldBy.REVIEWER,
                    held_base=current.held_base,
                    cause=Cause.REVIEWER_HOLD,
                )
    except BranchBusy as error:
        return _deferred(f"hold #{pr}", unit, error, log)
    log(f"hold #{pr}: {unit.id} is held, the pipeline will not touch it")
    return True


def on_release(
    pr: int,
    *,
    repo: str,
    store: UnitStore,
    claim: Claim = _unclaimed,
    restack: Restack | None = None,
    rebase_cap: int | None = None,
    resume: Resume = _no_thread,
    log: Log = print,
) -> bool:
    """The hold label has come off: a unit it held goes back to waiting for review.

    Only a hold the label caused. One the review loop, a depth cap or the
    toolchain made has nothing to do with it, and stays. A depth hold the label
    took over goes back to being one: held for depth again, or, when a merge
    during the label brought it within the cap, restacked from the branch it
    was still on. What arrived during the hold is not touched here: the poller
    delivers it as it would to any unit waiting for review.
    """
    unit = _find(store, repo, pr)
    if unit is None:
        log(f"release #{pr}: no unit recorded for it in {repo}, ignoring")
        return True

    restored: StoredUnit | None = None
    try:
        if (refusal := _release_refused(store.get(unit.id), pr)) is not None:
            log(refusal)
            return True
        if resume(unit, "release", "", ""):
            log(f"release #{pr}: {unit.id} is waiting for review again")
            return True
        with claim(unit):
            current = store.get(unit.id)
            if (refusal := _release_refused(current, pr, under_claim=True)) is not None:
                log(refusal)
                return True
            if restore_depth_hold(store, current):
                restored = current
            else:
                store.set_state(unit.id, IN_REVIEW, note="hold label removed", cause=Cause.RELEASED)
        if restored is not None:
            old_base = restored.held_base
            if (
                rebase_cap is None
                or restack is None
                or reconsider_depth_hold(
                    restored,
                    old_base,
                    store.all(),
                    store=store,
                    restack=restack,
                    claim=claim,
                    rebase_cap=rebase_cap,
                    log=log,
                )
            ):
                log(f"release #{pr}: {unit.id} is held for depth again")
                return True
    except BranchBusy as error:
        return _deferred(f"release #{pr}", unit, error, log)
    log(f"release #{pr}: {unit.id} is waiting for review again")
    return True


def _release_refused(unit: StoredUnit, pr: int, *, under_claim: bool = False) -> str | None:
    """The log line saying why a release changes nothing; None when it applies.

    Before the claim a unit being built passes, so the claim defers the event
    and the poller reports it again; under the claim nothing is building it, so a
    unit still stored `running` was never held and there is nothing to release.
    """
    if unit.state == RUNNING and not under_claim:
        return None
    if unit.state != HELD:
        return f"release #{pr}: {unit.id} is {unit.state}, not held, nothing to release"
    if unit.held_by_the_label:
        return None
    return (
        f"release #{pr}: {unit.id} is held by {held_cause(unit)}, not the label's, leaving it held"
    )


def on_rework(
    pr: int,
    *,
    repo: str,
    reason: str,
    pull: PullRequest | None = None,
    store: UnitStore,
    fetch_review: Callable[[int], Review] | None = None,
    fetch_checks: Callable[[PullRequest | None], str] | None = None,
    claim: Claim = _unclaimed,
    waiting: set[tuple[str, str]] | None = None,
    resume: Resume = _no_thread,
    rework: ReworkKind | None = None,
    log: Log = print,
) -> bool:
    """Put a unit back in the queue with what review asked for.

    False when the unit did not take it (it is held, or being built): the
    poller then keeps the event to report again. `waiting` remembers which
    held units have said so, so a comment that waits is logged once.

    The reviewer's own words, not just "new comment": the tick that reworks a
    unit is a different process from the poll that heard the review, and a
    rebuild that doesn't know what was asked for spends a full unit's budget
    reproducing the same code.
    """
    unit = _find(store, repo, pr)
    if unit is None:
        log(f"rework #{pr}: no unit recorded for it in {repo}, ignoring")
        return True

    heard: set[tuple[str, str]] = waiting if waiting is not None else set()
    try:
        if (
            taken := _not_for_now(store.get(unit.id), pr=pr, reason=reason, waiting=heard, log=log)
        ) is not None:
            return taken

        def feedback() -> tuple[str, bool, tuple[str, ...]]:
            return _feedback(
                pr=pr,
                reason=reason,
                rework=rework,
                pull=pull,
                fetch_review=fetch_review,
                fetch_checks=fetch_checks,
            )

        if resume(unit, "rework", reason, feedback, rework=rework):
            log(f"rework #{pr}: {unit.id} resumed — {reason}")
            return True
        with claim(unit):
            # Re-read under the lock: a build that has just ended moved it.
            current = store.get(unit.id)
            if (
                taken := _not_for_now(current, pr=pr, reason=reason, waiting=heard, log=log)
            ) is not None:
                return taken
            # Only now, with the unit taking it: a deferred rework asks for nothing.
            words, from_person, _ = feedback()
            taken = _requeue(
                current,
                pr=pr,
                reason=reason,
                rework=rework,
                store=store,
                feedback=words,
                from_person=from_person,
                log=log,
            )
    except BranchBusy as error:
        return _deferred(f"rework #{pr}", unit, error, log)
    return taken


def on_rerun_checks(
    pr: int,
    *,
    repo: str,
    pull: PullRequest,
    store: UnitStore,
    rerun: Callable[[PullRequest], None],
    log: Log = print,
) -> bool:
    """Ask the host to run a unit's cancelled checks again, without an agent,
    up to `limits.max_check_reruns` times per head commit.

    The count is on the stored unit, against the commit last pushed: it starts
    again when the head moves. Past the bound nothing is asked for and the unit
    is left in review: a host that keeps cancelling says nothing about the code.
    """
    from agent_build_kit.config import active

    unit = _find(store, repo, pr)
    if unit is None:
        log(f"rerun #{pr}: no unit recorded for it in {repo}, ignoring")
        return True
    if unit.state in (HELD, SATISFIED):
        # A held unit is a person's, and a satisfied one is closing: neither
        # has CI the runner may touch.
        log(f"rerun #{pr}: {unit.id} is {unit.state}, leaving the checks")
        return True

    head = unit.pushed or ""
    done = unit.check_reruns if unit.check_rerun_head == head else 0
    limit = active().limits.max_check_reruns
    names = ", ".join(cancelled_names(pull.checks))
    if done >= limit:
        log(
            f"rerun #{pr}: {unit.id} at {head}: the host keeps cancelling the checks "
            f"({names}) after {limit} re-runs, leaving them"
        )
        return True
    log(f"rerun #{pr}: {unit.id} at {head}: re-run {done + 1} of {limit} of {names}")
    try:
        rerun(pull)
    except RuntimeError as error:
        log(f"rerun #{pr}: the host refused: {error}")
        return True
    store.record_check_rerun(unit.id, head, done + 1)
    return True


def _not_for_now(
    unit: StoredUnit, *, pr: int, reason: str, waiting: set[tuple[str, str]], log: Log
) -> bool | None:
    """What a rework does to a unit that cannot take it now, None when it can.

    A held unit does not take it: the event is reported again once it is
    released, rather than recorded as handled and lost. A satisfied unit has
    nothing to rework, and the event is consumed.
    """
    if unit.state == HELD:
        # A human has taken it over; requeuing would push over work they are
        # in the middle of. Said once per unit and event, as the poll comes
        # round every few minutes until it is released.
        if (unit.id, reason) not in waiting:
            waiting.add((unit.id, reason))
            log(f"rework #{pr}: {unit.id} is held, ignoring")
        return False
    waiting.discard((unit.id, reason))
    if unit.state == SATISFIED:
        # See `on_closed`: requeuing it would judge a branch this unit never
        # built, over feedback aimed at a pull request that is closing.
        log(f"rework #{pr}: {unit.id} is satisfied, ignoring")
        return True
    return None


def _feedback(
    *,
    pr: int,
    reason: str,
    rework: ReworkKind | None,
    pull: PullRequest | None,
    fetch_review: Callable[[int], Review] | None,
    fetch_checks: Callable[[PullRequest | None], str] | None,
) -> tuple[str, bool, tuple[str, ...]]:
    """What a rework hands the agent, whether it is a person's words, and the ids of the
    comments those words came from, fetched only now there is something to act on."""
    # A poll cannot afford a second request per PR, so the reviewer's actual
    # words are fetched only now, when there is something to act on. They are
    # often the only content there is: a review's bodies can both be empty,
    # with the whole review one inline comment on a line, which `gh pr list`
    # does not return at all.
    if rework is ReworkKind.FAILING_CHECKS:
        # CI, not a reviewer: what failed and its log, and nothing else. The
        # review comments on the PR were answered already, and replaying them
        # would have the rework redo old work instead of fixing the build.
        logs = fetch_checks(pull) if fetch_checks else ""
        return f"{reason}\n\n{logs}".strip(), False, ()
    if rework is ReworkKind.CONFLICT:
        # Nor a reviewer: the branch no longer merges into its base, and the
        # restack at the start of the run does the rebase. Replaying the
        # PR's answered review would bury that under old work.
        return (
            f"{reason}: the branch has been moved onto its current base at the "
            "start of this run; check that the resolution kept this unit's "
            "behaviour and its tests pass, and do not rebase or reset the "
            "branch yourself.",
            False,
            (),
        )
    review = fetch_review(pr) if fetch_review else Review()
    said = "\n".join([*review.lines, _latest_comment(pull)]).strip()
    # What the words were built from: the poller's listing and the notes just read, so a
    # comment posted since is not taken as given.
    listed = pull.conversation if pull else ()
    # The one place a person's words enter feedback; the reason alone is
    # the host's.
    return said or reason, bool(said), (*listed, *review.ids)


def _requeue(
    unit: StoredUnit,
    *,
    pr: int,
    reason: str,
    rework: ReworkKind | None,
    store: UnitStore,
    feedback: str,
    from_person: bool,
    log: Log,
) -> bool:
    """Requeue `unit`, which has taken the rework for `reason`."""
    store.set_feedback(
        unit.id, feedback, from_person=from_person, source=feedback_source_of(rework)
    )
    store.set_state(unit.id, PLANNED, note=f"rework requested: {reason}", cause=Cause.REWORK)
    log(f"rework #{pr}: {unit.id} requeued — {reason}")
    return True


def _check_fetcher(
    store: UnitStore, repo: str, number: int, fetch_checks: Callable[..., str] | None
) -> Callable[[PullRequest | None], str] | None:
    """Bind a PR's repo to the check-log fetcher, as `_review_fetcher` does."""
    if fetch_checks is None:
        return None
    unit = _find(store, repo, number)
    if unit is None:
        return None
    return lambda pull: fetch_checks(unit.repo, pull)


def _review_fetcher(
    store: UnitStore, repo: str, pr: int, fetch: Callable[..., Review] | None
) -> Callable[[int], Review] | None:
    """Bind the fetcher to the repo the PR's unit lives in."""
    if fetch is None:
        return None
    unit = _find(store, repo, pr)
    if unit is None:
        return None
    return lambda number: fetch(unit.repo, number)


def _latest_comment(pull: PullRequest | None) -> str:
    """The newest comment's text, which is what the reviewer actually wrote.

    A failing check dispatches rework too and carries no comment, so the
    caller's `reason` stands in for it.

    The pipeline's own posts are skipped, as in `review_lines`: read back as
    review, a rework would be handed its own summary.
    """
    comments = [
        body
        for raw in (pull.comment_bodies if pull else ())
        if (body := raw.strip()) and MARKER not in body
    ]
    return comments[-1] if comments else ""


def build_restack(
    *,
    repos: dict[str, Path],
    store: UnitStore,
    root: Path,
    move: Callable[..., Moved] | None = None,
    tier1: Callable[..., tuple[bool, str]] | None = None,
    push: Callable[..., str] | None = None,
    retarget: Callable[..., None] | None = None,
    comment: Callable[..., None] | None = None,
    diff_id: Callable[[Path, str, str], str] | None = None,
    head_of: Callable[[Path, str], str] | None = None,
    remote_head_of: Callable[[Path, str], str | None] | None = None,
    adopt: Callable[..., str] | None = None,
    posts_root: Path | None = None,
) -> Restack:
    """Move one child branch onto its new base, for real.

    The order is the guarantee. The rebase rewrites every commit on the
    branch, so the checks run again **before** the push: putting an unverified
    head in front of a reviewer, under the green tick the old head earned, is
    worse than leaving the branch where it was.

    And nothing reaches a PR that review has not approved. A rebase that
    applied cleanly leaves the unit's own diff byte-for-byte what review
    approved, so the approval carries over to the new head and it is pushed.
    If the diff changed at all — a conflict the resolver rewrote — or review
    never approved the head being moved, the unit goes back through review
    instead, and the runner pushes once it passes.
    """
    move = move or resolved_move
    tier1 = tier1 or _default_tier1
    push = push or _default_push
    retarget = retarget or _default_retarget
    comment = comment or partial(_default_comment, posts_root=posts_root)
    diff_id = diff_id or restack_diff_id
    head_of = head_of or (lambda repo, branch: git(repo, "rev-parse", branch).stdout.strip())
    remote_head_of = remote_head_of or remote_head
    adopt = adopt or adopt_host_head

    def restack(
        *, branch: str, old_base: str, new_base: str, child: StoredUnit, parent: StoredUnit
    ) -> None:
        repo = repos[child.repo]
        # Prefer the unit's own worktree if it still exists: the checks then
        # run where the branch is checked out, rather than on whatever the
        # main clone happens to have in its working tree. `root` is
        # `spec_worktree_root` — outside the planning repo, see settings.
        worktree = worktree_path(repo, branch, root)
        cwd = worktree if worktree.exists() else repo

        # A satisfied parent added no commits, so a branch that already holds
        # its new base needs no move: it was cut from the parent's predecessor,
        # or moved by an earlier release. Its PR still points at the satisfied
        # unit's branch, which is closed next, so that moves, unless it already
        # has.
        if (
            parent.state == SATISFIED
            and git(
                repo, "merge-base", "--is-ancestor", local_ref(new_base), branch, check=False
            ).returncode
            == 0
        ):
            if child.pr and not pr_based_on(child, new_base):
                retarget(child.pr, new_base, repo=child.repo)
            return

        # Retargeted before anything else, and whatever the adopt or the move
        # does: with its base branch merged away, a PR left pointing at it
        # would be closed by GitHub.
        if child.pr:
            retarget(child.pr, new_base, repo=child.repo)

        # The pipeline is not the only writer: after a stack merge the host
        # rebases the PRs above and force-pushes their branches itself. So the
        # branch on the host is inspected too - if it no longer holds what was
        # last pushed, review never saw its head. Unknown ("") is not moved.
        remote = remote_head_of(repo, branch)
        last_pushed = child.pushed
        if remote and last_pushed and remote != last_pushed and head_of(repo, branch) == remote:
            # Not moved by anyone: a push of ours whose recording was lost.
            store.record_push(child.id, remote)
            last_pushed = remote
        elif remote and last_pushed and remote != last_pushed:
            # Adopted, not overwritten: the local branch is brought to the
            # host's head, so review sees what the host has and the next
            # lease names it.
            before = head_of(repo, branch)
            adopted = adopt(
                repo,
                branch,
                host_head=remote,
                last_pushed=last_pushed,
                cwd=cwd,
                base=local_ref(new_base),
            )
            store.record_push(child.id, remote)
            if adopted == before:
                # The host holds the same change, so what review approved
                # stands: only the lease moves, and the restack goes on.
                last_pushed = remote
            else:
                # The old approval was for a different commit.
                store.record_approval(child.id, "")
                # Not moved here: the host already rebased it onto the trunk, so
                # `old_base..branch` now spans trunk commits that are not the
                # unit's, and replaying them only invites conflicts. If it was a
                # person rather than a stack merge that moved it, the runner's own
                # restack moves a branch that no longer holds its base.
                store.set_state(
                    child.id,
                    PLANNED,
                    note=f"not restacked onto {new_base}: "
                    "the host moved its branch off the approved commit",
                    cause=Cause.RESTACK_DEFERRED,
                )
                return

        was_approved = bool(child.approved) and head_of(repo, branch) == child.approved
        diff_before = diff_id(repo, old_base, branch)

        # Both sides are planned work, so the resolver is told what each was
        # for rather than left to infer it from the diff — see `resolved_move`,
        # which a resuming unit's own restack shares.
        try:
            moved = move(
                repo,
                branch,
                new_base=local_ref(new_base),
                old_base=old_base,
                moving_unit=child.id,
                moving_intent=child.title,
                onto_unit=parent.id,
                onto_intent=parent.title,
            )
        except RestackConflict as error:
            # Left unmoved for the runner, whose own restack meets the same
            # conflict and hands it to the adapt step — which ports the work and
            # accounts for each of the unit's tests.
            store.set_state(
                child.id,
                PLANNED,
                note=f"restack onto {new_base} could not be merged; the adapt step ports it: "
                f"{str(error)[:300]}",
                cause=Cause.RESTACK_CONFLICT,
            )
            return
        except (AgentRateLimited, AgentInterrupted) as error:
            # The resolver could not run, which says nothing about the branch.
            # Not raised on: the merge is handled once, and the parent's branch
            # goes next, so the runner's own restack retries it — pausing the
            # tick if the window is still spent.
            why = "a rate limit" if isinstance(error, AgentRateLimited) else "an interrupted run"
            store.set_state(
                child.id,
                PLANNED,
                note=f"restack onto {new_base} deferred for {why}; the runner retries it: "
                f"{str(error)[:300]}",
                cause=Cause.RESTACK_DEFERRED,
            )
            return

        unchanged = (
            was_approved
            and not moved.resolved
            and diff_before
            and diff_id(repo, local_ref(new_base), branch) == diff_before
        )
        if not unchanged:
            if moved.resolved:
                files = ", ".join(moved.resolved)
                why = f"resolving {files} changed its diff"
                store.set_predecessor_note(
                    child.id,
                    PREDECESSOR_NOTE.format(
                        onto_unit=parent.id,
                        how=f"moving onto it needed conflict resolution in {files}",
                        decisions="",
                    ),
                )
            elif was_approved:
                why = "the restack changed its diff"
            else:
                why = "review never approved its head"
            store.set_state(
                child.id,
                PLANNED,
                note=f"restacked onto {new_base}, not pushed: {why}",
                cause=Cause.RESTACK_DEFERRED,
            )
            return

        context = spans.current_unit.set((child.id, child.change, "restack", 0))
        try:
            passed, output = tier1(cwd=cwd, base=local_ref(new_base))
        finally:
            spans.current_unit.reset(context)
        if not passed:
            raise RuntimeError(
                f"{branch} moved onto {new_base} but its checks fail — "
                f"left unpushed, with the reviewable head still on the remote:\n{output}"
            )

        store.record_approval(child.id, head_of(repo, branch))
        sha = push(repo, branch, last_pushed=last_pushed)
        store.record_push(child.id, sha)

        if child.pr:
            comment(
                child.pr,
                blast_radius_note(
                    branch=branch,
                    old_base=old_base,
                    new_base=new_base,
                    reason=f"{parent.id} merged",
                ),
                repo=child.repo,
            )

    return restack


def _default_tier1(*, cwd: Path, base: str) -> tuple[bool, str]:
    return build_tier1()(cwd=cwd, base=base)


def _default_push(repo: Path, branch: str, *, last_pushed: str | None) -> str:
    return push_with_lease(repo, branch, last_pushed=last_pushed)


def _default_retarget(pr: int, new_base: str, *, repo: str) -> None:
    forge, repo_id = forges.for_repo(repo)
    forge.update_pr(repo_id, pr, base=new_base)


def build_retarget() -> Callable[[StoredUnit, str], None]:
    """Point a unit's PR at a new base without touching its tree: what a
    merge can still do for a child whose build is running."""

    def retarget(unit: StoredUnit, new_base: str) -> None:
        if unit.pr:
            _default_retarget(unit.pr, new_base, repo=unit.repo)

    return retarget


def pr_based_on(unit: StoredUnit, base: str) -> bool:
    """Whether the unit's pull request already points at `base`, as the host
    reports it. True when it has none, nothing then needing to move; False when
    the host cannot say, so the caller moves it."""
    if not unit.pr:
        return True
    try:
        forge, repo_id = forges.for_repo(unit.repo)
        pulls = forge.list_prs(repo_id, head_prefix=branch_name(unit))
    except Exception:  # noqa: BLE001
        return False
    return any(pull.number == unit.pr and pull.base == base for pull in pulls)


def build_settled(repos: dict[str, Path]) -> Callable[[StoredUnit, str], bool]:
    """What `release_children` asks before moving a child: whether its branch
    already holds `base` and its pull request already points there."""

    def settled(child: StoredUnit, base: str) -> bool:
        held = git(
            repos[child.repo],
            "merge-base",
            "--is-ancestor",
            local_ref(base),
            branch_name(child),
            check=False,
        )
        return held.returncode == 0 and pr_based_on(child, base)

    return settled


def _default_comment(pr: int, body: str, *, repo: str, posts_root: Path | None) -> None:
    """Post as the pipeline: marked, and recorded so the poller skips it.

    Recorded by the ids the forge reports, because a comment the poller cannot
    recognise as the pipeline's own reads as a reviewer's and sends the unit
    to rework over it.
    """
    forge, repo_id = forges.for_repo(repo)
    posted = forge.post_comment(repo_id, pr, body=f"{body}\n{MARKER}")
    if posts_root is not None and posted:
        record_posts(posts_root, forges.key(repo_id), pr, posted)


def _load_waiting(path: Path) -> set[tuple[str, str]]:
    try:
        return {(unit_id, reason) for unit_id, reason in json.loads(path.read_text())}
    except (OSError, ValueError, TypeError):
        return set()


def _save_waiting(path: Path, store: UnitStore, waiting: set[tuple[str, str]]) -> None:
    """Record `waiting`, less the units no longer held: a unit that is released
    has no wait left to remember, whether or not it took the event."""
    held = {unit.id for unit in store.all() if unit.state == HELD}
    kept = sorted(entry for entry in waiting if entry[0] in held)
    if kept == sorted(_load_waiting(path)):
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(kept))


def build_dispatch(
    store: UnitStore,
    *,
    restack: Restack,
    remove_worktree: Callable[..., None] | None = None,
    delete_branch: Callable[..., None] | None = None,
    fetch_review: Callable[..., Review] | None = None,
    fetch_checks: Callable[..., str] | None = None,
    rerun_checks: Callable[..., None] | None = None,
    claim: Claim = _unclaimed,
    retarget: Callable[[StoredUnit, str], None] | None = None,
    rebase_cap: int | None = None,
    waiting_path: Path | None = None,
    resume: Resume = _no_thread,
    log: Log = print,
) -> Callable[..., bool]:
    """The callable `pr_poller` hands each event to.

    The event names are the poller's contract; an unhandled one is logged
    rather than dropped, because silence here is indistinguishable from a
    working pipeline with nothing to do. False means the event was deferred
    because its unit is being built, and the poller keeps it to report again.

    `repo` is the repo the event was read from, and required: a pull request
    number means nothing without it. One dispatch serves every repo's poller,
    so whoever builds the pollers binds each one's repo (see `cli.poll_all`).

    `waiting_path` is where the held units that have already said they are
    waiting are recorded. A dispatch is built afresh for every poll, so the
    record has to outlive it, or a comment waiting on a hold is logged on
    every poll for as long as the hold lasts. Without a path it lives only as
    long as this dispatch.
    """

    waiting: set[tuple[str, str]] = set()

    def dispatch(event: str, number: int, *, repo: str, **kwargs) -> bool:
        if event == "merged":
            return on_merged(
                number,
                repo=repo,
                store=store,
                restack=restack,
                remove_worktree=remove_worktree,
                delete_branch=delete_branch,
                claim=claim,
                retarget=retarget,
                rebase_cap=rebase_cap,
                resume=resume,
                log=log,
            )
        if event == "closed":
            return on_closed(number, repo=repo, store=store, claim=claim, resume=resume, log=log)
        if event == "hold":
            return on_hold(number, repo=repo, store=store, claim=claim, resume=resume, log=log)
        if event == "release":
            return on_release(
                number,
                repo=repo,
                store=store,
                claim=claim,
                restack=restack,
                rebase_cap=rebase_cap,
                resume=resume,
                log=log,
            )
        if event == "rework":
            known = _load_waiting(waiting_path) if waiting_path else waiting
            taken = on_rework(
                number,
                repo=repo,
                reason=kwargs.get("reason", "unspecified"),
                pull=kwargs.get("pull"),
                store=store,
                fetch_review=_review_fetcher(store, repo, number, fetch_review),
                fetch_checks=_check_fetcher(store, repo, number, fetch_checks),
                claim=claim,
                waiting=known,
                resume=resume,
                rework=kwargs.get("rework"),
                log=log,
            )
            if waiting_path:
                _save_waiting(waiting_path, store, known)
            return taken
        if event == "rerun_checks":
            if rerun_checks is None or kwargs.get("pull") is None:
                log(f"rerun #{number} in {repo}: no way to ask the host, leaving the checks")
                return True
            return on_rerun_checks(
                number,
                repo=repo,
                pull=kwargs["pull"],
                store=store,
                rerun=lambda pull: rerun_checks(repo, pull),
                log=log,
            )
        log(f"unhandled poller event {event!r} for #{number} in {repo}")
        return True

    return dispatch
