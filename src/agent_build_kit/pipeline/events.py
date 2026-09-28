"""What the pipeline does when GitHub tells it something changed.

`gh_poller` watches PRs and names what happened; this decides what to do about
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
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from functools import partial
from pathlib import Path

from agent_build_kit.pipeline.pr_replies import MARKER, record_posts
from agent_build_kit.pipeline.restack import (
    Moved,
    RestackConflict,
    blast_radius_note,
    push_with_lease,
    resolved_move,
    retarget_pr,
)
from agent_build_kit.pipeline.restack import diff_id as restack_diff_id
from agent_build_kit.pipeline.shell import gh, gh_json, git, repo_slug
from agent_build_kit.pipeline.stack_runner import PREDECESSOR_NOTE
from agent_build_kit.pipeline.unit_store import StoredUnit, UnitStore
from agent_build_kit.pipeline.units import (
    CLOSED,
    HELD,
    IN_FLIGHT,
    MERGED,
    PLANNED,
    base_of,
    branch_name,
    local_ref,
)
from agent_build_kit.pipeline.wiring import build_tier1
from agent_build_kit.pipeline.workspaces import remove_worktree as drop_worktree
from agent_build_kit.pipeline.workspaces import worktree_path

Log = Callable[[str], None]
Restack = Callable[..., None]


def _find(store: UnitStore, pr: int) -> StoredUnit | None:
    for unit in store.all():
        if unit.pr == pr:
            return unit
    return None


def on_merged(
    pr: int,
    *,
    store: UnitStore,
    restack: Restack,
    remove_worktree: Callable[..., None] | None = None,
    delete_branch: Callable[..., None] | None = None,
    log: Log = print,
) -> None:
    """Record the merge, move what was stacked on it, then clean up after it."""
    remove_worktree = remove_worktree or (lambda repo, branch: None)
    delete_branch = delete_branch or (lambda repo, branch: None)
    merged = _find(store, pr)
    if merged is None:
        # Someone else's PR on a spec/ branch, or a unit dropped from the
        # store. Restacking against a unit we don't know moves the wrong
        # branch, so do nothing at all.
        log(f"merged #{pr}: no unit recorded for it, ignoring")
        return

    store.set_state(merged.id, MERGED)
    log(f"merged #{pr}: {merged.id}")

    # Re-read: the children's new bases are worked out from the graph with the
    # merge already applied, which is what makes a merged parent drop out of
    # `base_of` instead of still being offered as a base.
    graph = store.all()
    old_base = branch_name(merged)

    for child in _children_of(merged, graph):
        new_base = base_of(child, graph)
        if new_base == old_base:
            continue  # Nothing to do: it is not what this child sat on.

        try:
            restack(
                branch=branch_name(child),
                old_base=old_base,
                new_base=new_base,
                child=child,
                parent=merged,
            )
        except Exception as error:  # noqa: BLE001
            # Left where it is, still open, still based on the old branch. A
            # human resolves it; the rest of the stack is not held up for it.
            log(f"{child.id}: restack onto {new_base} failed — {type(error).__name__}: {error}")
            continue

        log(f"{child.id}: restacked onto {new_base}")

    # Last, and only the merged unit's own: a child still has an open PR and
    # may yet be restacked or reworked in its tree. Nothing else ever removes
    # one, so without this each unit leaves a full checkout behind for good.
    try:
        remove_worktree(merged.repo, old_base)
    except Exception as error:  # noqa: BLE001
        # `remove_worktree` refuses a dirty tree on purpose — uncommitted work
        # there may be the only copy. The merge already happened either way,
        # and the branch stays too: deleting it would strand that work on a
        # checkout with no ref pointing at it.
        log(f"{merged.id}: worktree and branch left in place — {error}")
        return

    try:
        # Only now: a branch checked out in a worktree cannot be deleted, so
        # the order is a requirement rather than a preference.
        delete_branch(merged.repo, old_base)
    except Exception as error:  # noqa: BLE001
        log(f"{merged.id}: branch {old_base} left in place — {error}")


def _children_of(parent: StoredUnit, graph: list[StoredUnit]) -> list[StoredUnit]:
    """The still-open units stacked on `parent`, in the same repo.

    A cross-repo dependent is never stacked on it — stacks can't span repos —
    so it has nothing to move; `ready_units` makes it wait for the merge
    instead.
    """
    return [
        unit
        for unit in graph
        if parent.id in unit.depends_on
        and unit.repo == parent.repo
        and unit.state in IN_FLIGHT
        and unit.branch
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


def review_lines(*, reviews: list[dict], comments: list[dict]) -> list[str]:
    """The reviewer's words, skipping anything GitHub says is outdated.

    An inline comment whose code has changed comes back with `line: null` and
    its old position in `original_line`. After a rework that is precisely the
    comment the rework addressed, so replaying it tells the agent to redo work
    it has already done — and every later round would carry every earlier
    comment with it. A comment on a line goes outdated the moment its fix
    lands.

    A submitted review's own body is not anchored to a line, so it has nothing
    to go stale against and is always included.

    The pipeline's own replies (marked with `pr_replies.MARKER`) are left out:
    they answer the review, and read back as review they would have the next
    rework respond to itself. Each inline comment carries its id, which is
    how the rework says which thread each of its replies belongs in.
    """
    out = [
        body for r in reviews if (body := str(r.get("body") or "").strip()) and MARKER not in body
    ]
    for comment in comments:
        body = str(comment.get("body") or "").strip()
        if body and MARKER not in body and comment.get("line") is not None:
            where = f"{comment.get('path', '?')}:{comment['line']}"
            tag = f"[comment {comment['id']}] " if comment.get("id") else ""
            out.append(f"{tag}{where} — {body}")
    return [line for line in out if line]


def build_fetch_review(repos: dict[str, Path]) -> Callable[..., list[str]]:
    """The reviewer's words on a PR: review bodies, then live inline comments.

    Two requests, made only when a rework is already being dispatched. Adding
    them to the poll itself would be one extra request per open PR per tick.
    """

    def fetch(repo: str, pr: int) -> list[str]:
        slug = repo_slug(repo)

        # The repo is named in the path, not with --repo, so the slug is
        # passed explicitly — otherwise the call would run as whichever
        # account happens to be active.
        def items(kind: str) -> list[dict]:
            found = gh_json(
                ["gh", "api", "--paginate", f"repos/{slug}/pulls/{pr}/{kind}"], slug=slug
            )
            return found if isinstance(found, list) else []

        return review_lines(reviews=items("reviews"), comments=items("comments"))

    return fetch


# The part of a failed job's log a fix needs: the failure and what led to it.
CHECK_LOG_CHARS = 6000
RUN_URL = re.compile(r"/actions/runs/(?P<run>\d+)")
LOG_PREFIX = re.compile(r"^[^\t]*\t[^\t]*\t\ufeff?\d{4}-\d\d-\d\dT[\d:.]+Z ?")


def build_fetch_check_logs() -> Callable[..., str]:
    """The failed CI jobs' logs for a PR, for the rework that fixes them.

    The poller already sends a unit back when a check starts failing, but the
    rework used to get only "failing checks: <name>" — and when the failure
    is a test tier 1 never ran, nothing local can say why.
    """

    def fetch(repo: str, pull: dict | None) -> str:
        slug = repo_slug(repo)
        failed = [
            check
            for check in (pull or {}).get("statusCheckRollup") or []
            if str(check.get("conclusion", "")).upper() in ("FAILURE", "TIMED_OUT", "CANCELLED")
        ]
        runs = sorted(
            {m["run"] for c in failed if (m := RUN_URL.search(str(c.get("detailsUrl", ""))))}
        )
        parts = []
        for run in runs:
            result = gh(["gh", "run", "view", run, "--repo", slug, "--log-failed"], slug=slug)
            text = "\n".join(LOG_PREFIX.sub("", line) for line in result.stdout.splitlines())
            names = ", ".join(str(c.get("name")) for c in failed)
            tail = text[-CHECK_LOG_CHARS:]
            parts.append(f"CI run {run} ({names}), end of its failed log:\n```\n{tail}\n```")
        return "\n\n".join(parts)

    return fetch


def build_remove_worktree(repos: dict[str, Path], *, root: Path) -> Callable[..., None]:
    """Drop a finished unit's worktree, keeping its branch and any dirty work.

    `workspaces.remove_worktree` does not force: a tree with uncommitted
    changes is left for a human, because what is in it may be the only copy.
    """

    def remove(repo: str, branch: str) -> None:
        drop_worktree(repos[repo], branch, root=root)

    return remove


def on_closed(pr: int, *, store: UnitStore, log: Log = print) -> None:
    """Record that a PR was closed without merging.

    Deliberately not propagated to whatever was stacked on it: closing is a
    decision about one unit, and the branches above it hold work that nobody
    asked to drop.
    """
    unit = _find(store, pr)
    if unit is None:
        log(f"closed #{pr}: no unit recorded for it, ignoring")
        return

    store.set_state(unit.id, CLOSED)
    log(f"closed #{pr}: {unit.id} — anything stacked on it is left as it stands")


def on_hold(pr: int, *, store: UnitStore, log: Log = print) -> None:
    """A reviewer has taken the unit over. Nothing automatic touches it again."""
    unit = _find(store, pr)
    if unit is None:
        log(f"hold #{pr}: no unit recorded for it, ignoring")
        return

    store.set_state(unit.id, HELD)
    log(f"hold #{pr}: {unit.id} is held, the pipeline will not touch it")


def on_rework(
    pr: int,
    *,
    reason: str,
    pull: dict | None = None,
    store: UnitStore,
    fetch_review: Callable[[int], list[str]] | None = None,
    fetch_checks: Callable[[dict | None], str] | None = None,
    log: Log = print,
) -> None:
    """Put a unit back in the queue with what review asked for.

    The reviewer's own words, not just "new comment": the tick that reworks a
    unit is a different process from the poll that heard the review, and a
    rebuild that doesn't know what was asked for spends a full unit's budget
    reproducing the same code.
    """
    unit = _find(store, pr)
    if unit is None:
        log(f"rework #{pr}: no unit recorded for it, ignoring")
        return

    if unit.state == HELD:
        # A human has taken it over; requeuing would push over work they are
        # in the middle of.
        log(f"rework #{pr}: {unit.id} is held, ignoring")
        return

    # A poll cannot afford a second request per PR, so the reviewer's actual
    # words are fetched only now, when there is something to act on. They are
    # often the only content there is: a review's bodies can both be empty,
    # with the whole review one inline comment on a line, which `gh pr list`
    # does not return at all.
    if reason.startswith("failing checks"):
        # CI, not a reviewer: what failed and its log, and nothing else. The
        # review comments on the PR were answered already, and replaying them
        # would have the rework redo old work instead of fixing the build.
        logs = fetch_checks(pull) if fetch_checks else ""
        feedback = f"{reason}\n\n{logs}".strip()
    else:
        words = list(fetch_review(pr)) if fetch_review else []
        feedback = "\n".join([*words, _latest_comment(pull)]).strip() or reason
    store.set_feedback(unit.id, feedback)
    # New feedback outranks where a paused unit meant to pick up: resuming at
    # a review would skip the rework this feedback asks for, and a pass would
    # then clear the feedback unread — dropping a review left while its unit
    # was paused before review.
    store.set_state(unit.id, PLANNED, note=f"rework requested: {reason}", resume_from="")
    log(f"rework #{pr}: {unit.id} requeued — {reason}")


def _check_fetcher(
    store: UnitStore, number: int, fetch_checks: Callable[..., str] | None
) -> Callable[[dict | None], str] | None:
    """Bind a PR's repo to the check-log fetcher, as `_review_fetcher` does."""
    if fetch_checks is None:
        return None
    unit = _find(store, number)
    if unit is None:
        return None
    return lambda pull: fetch_checks(unit.repo, pull)


def _review_fetcher(
    store: UnitStore, pr: int, fetch: Callable[..., list[str]] | None
) -> Callable[[int], list[str]] | None:
    """Bind the fetcher to the repo the PR's unit lives in."""
    if fetch is None:
        return None
    unit = _find(store, pr)
    if unit is None:
        return None
    return lambda number: fetch(unit.repo, number)


def _latest_comment(pull: dict | None) -> str:
    """The newest comment's text, which is what the reviewer actually wrote.

    A failing check dispatches rework too and carries no comment, so the
    caller's `reason` stands in for it.

    The pipeline's own posts are skipped, as in `review_lines`: read back as
    review, a rework would be handed its own summary.
    """
    comments = [
        body
        for c in (pull or {}).get("comments") or []
        if (body := str(c.get("body", "")).strip()) and MARKER not in body
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

        was_approved = bool(child.approved) and head_of(repo, branch) == child.approved
        diff_before = diff_id(repo, old_base, branch)

        # Retargeted before anything else, and whatever the move does: with
        # its base branch merged away, a PR left pointing at it would be
        # closed by GitHub.
        if child.pr:
            retarget(child.pr, new_base, repo_slug=repo_slug(child.repo))

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
                resume_from="rework_review",
            )
            return

        passed, output = tier1(cwd=cwd, base=local_ref(new_base))
        if not passed:
            raise RuntimeError(
                f"{branch} moved onto {new_base} but its checks fail — "
                f"left unpushed, with the reviewable head still on the remote:\n{output}"
            )

        store.record_approval(child.id, head_of(repo, branch))
        sha = push(repo, branch, last_pushed=child.pushed)
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
                repo_slug=repo_slug(child.repo),
            )

    return restack


def _default_tier1(*, cwd: Path, base: str) -> tuple[bool, str]:
    return build_tier1()(cwd=cwd, base=base)


def _default_push(repo: Path, branch: str, *, last_pushed: str | None) -> str:
    return push_with_lease(repo, branch, last_pushed=last_pushed)


def _default_retarget(pr: int, new_base: str, *, repo_slug: str) -> None:
    retarget_pr(pr, new_base, repo_slug=repo_slug)


def _default_comment(pr: int, body: str, *, repo_slug: str, posts_root: Path | None) -> None:
    """Post as the pipeline: marked, and recorded so the poller skips it.

    `gh pr comment` left no id to record, so the poller read the pipeline's own
    note as a new comment and would have sent the unit to rework over it.
    """
    result = gh(
        [
            "gh",
            "api",
            "-X",
            "POST",
            f"repos/{repo_slug}/issues/{pr}/comments",
            "-f",
            f"body={body}\n{MARKER}",
        ],
        slug=repo_slug,
    )
    if posts_root is not None and not result.returncode:
        node_id = json.loads(result.stdout or "{}").get("node_id")
        if node_id:
            record_posts(posts_root, repo_slug, pr, [node_id])


def build_dispatch(
    store: UnitStore,
    *,
    restack: Restack,
    remove_worktree: Callable[..., None] | None = None,
    delete_branch: Callable[..., None] | None = None,
    fetch_review: Callable[..., list[str]] | None = None,
    fetch_checks: Callable[..., str] | None = None,
    log: Log = print,
) -> Callable[..., None]:
    """The callable `gh_poller` hands each event to.

    The event names are the poller's contract; an unhandled one is logged
    rather than dropped, because silence here is indistinguishable from a
    working pipeline with nothing to do.
    """

    def dispatch(event: str, number: int, **kwargs) -> None:
        if event == "merged":
            on_merged(
                number,
                store=store,
                restack=restack,
                remove_worktree=remove_worktree,
                delete_branch=delete_branch,
                log=log,
            )
        elif event == "closed":
            on_closed(number, store=store, log=log)
        elif event == "hold":
            on_hold(number, store=store, log=log)
        elif event == "rework":
            on_rework(
                number,
                reason=kwargs.get("reason", "unspecified"),
                pull=kwargs.get("pull"),
                store=store,
                fetch_review=_review_fetcher(store, number, fetch_review),
                fetch_checks=_check_fetcher(store, number, fetch_checks),
                log=log,
            )
        else:
            log(f"unhandled poller event {event!r} for #{number}")

    return dispatch
