"""The guard after a step that holds a rewrite request: the unit's base must be unchanged.

At the start of such a step the head the branch is on is recorded. After it, the base must still
be an ancestor of the head, every commit above the base must carry the unit trailer, and none may
be a merge commit. A branch that fails is put back at the recorded head and the step is returned
to the agent with the reason, as a failed check is.
"""

from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum
from pathlib import Path

from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.shell import git, git_out
from agent_build_kit.pipeline.unit_store import StoredRewriteRequest, UnitStore


class GuardCheck(StrEnum):
    """The check a rewrite failed."""

    BASE = "base"
    TRAILER = "trailer"
    MERGE = "merge"
    UNCHANGED = "unchanged"


class GuardVerdict(Frozen):
    """Whether the branch passed, and when it did not, the check, the reason naming the commits
    or the base, and that the branch was put back."""

    ok: bool
    check: GuardCheck | None = None
    reason: str = ""


class GuardedStep(Frozen):
    """How a guarded step ended: `ok` when the guard passed, how many times the step was
    returned to the agent, and the last verdict."""

    ok: bool
    returned: int
    verdict: GuardVerdict


def guard_rewrite(
    tree: Path,
    *,
    request: StoredRewriteRequest | None,
    base: str,
    started_at: str,
    unit_id: str,
    branch: str | None = None,
) -> GuardVerdict:
    """Check the branch checked out in `tree` after a step that started at `started_at` with
    `request`; `base` is where the unit's own commits begin, and `branch`, when given, is the
    branch the step began on, which HEAD must still be on. A step with no request is not
    checked. A failure moves the branch back to `started_at`."""
    if request is None:
        return GuardVerdict(ok=True)
    if branch is not None and _current_branch(tree) != branch:
        put_back(tree, branch=branch, started_at=started_at)
        return GuardVerdict(
            ok=False,
            check=GuardCheck.BASE,
            reason=f"HEAD is no longer on the unit's branch {branch}; the step must leave "
            "that branch checked out. The branch was put back to where the step began",
        )
    head = git_out(tree, "rev-parse", "HEAD")
    if head == started_at:
        return GuardVerdict(ok=True)
    origin = git_out(tree, "merge-base", base, started_at)
    verdict = _check(tree, origin=origin, base=base, head=head, unit_id=unit_id)
    if not verdict.ok:
        put_back(tree, branch=branch, started_at=started_at)
    return verdict


UNCHANGED_REASON = (
    "the step rewrote none of the unit's commits: every commit above the base that the step "
    "began with is still on the branch. Rewrite them (amend, or reset to the base and commit "
    "again) so the history has the shape asked for, and do not add commits on top. Edits in "
    "the tree are kept"
)


def _current_branch(tree: Path) -> str | None:
    """The branch HEAD is on, None when it is detached."""
    result = git(tree, "symbolic-ref", "--short", "-q", "HEAD", check=False)
    return result.stdout.strip() or None


def put_back(tree: Path, *, branch: str | None, started_at: str) -> None:
    """Abort any rebase, merge or cherry-pick left half done, check `branch` out again and
    move it to `started_at`."""
    for command in ("rebase", "merge", "cherry-pick"):
        git(tree, command, "--abort", check=False)
    if branch is not None:
        git(tree, "checkout", "-q", "-f", branch)
    git(tree, "reset", "-q", "--hard", started_at)


def _check(tree: Path, *, origin: str, base: str, head: str, unit_id: str) -> GuardVerdict:
    """The verdict on the commits between `origin`, where the unit began, and `head`."""
    chain = git_out(tree, "rev-list", "--reverse", "--first-parent", f"{origin}..{head}").split()
    below = git(tree, "merge-base", "--is-ancestor", origin, head, check=False).returncode != 0
    moved_in = (
        git_out(tree, "rev-parse", base) != origin
        and git(tree, "merge-base", "--is-ancestor", base, head, check=False).returncode == 0
    )
    if below or moved_in or (chain and git_out(tree, "rev-parse", f"{chain[0]}^") != origin):
        return GuardVerdict(
            ok=False,
            check=GuardCheck.BASE,
            reason=f"the unit's base {base} ({origin}) is no longer where the unit's commits "
            "begin; rewrite only the unit's own commits above it",
        )
    merges = git_out(tree, "rev-list", "--merges", f"{origin}..{head}").split()
    if merges:
        return GuardVerdict(
            ok=False,
            check=GuardCheck.MERGE,
            reason="merge commits above the base are not allowed: " + ", ".join(merges),
        )
    trailer = f"Unit: {unit_id}"
    log = git_out(
        tree,
        "log",
        "--reverse",
        "--format=%H%x09%(trailers:key=Unit,valueonly,separator=%x2C)",
        f"{origin}..{head}",
    )
    missing = []
    for line in log.splitlines():
        sha, _, values = line.partition("\t")
        if sha and unit_id not in [v.strip() for v in values.split(",")]:
            missing.append(sha)
    if missing:
        return GuardVerdict(
            ok=False,
            check=GuardCheck.TRAILER,
            reason=f"commits without the `{trailer}` trailer: " + ", ".join(missing),
        )
    return GuardVerdict(ok=True)


def run_guarded_step(
    tree: Path,
    *,
    request: StoredRewriteRequest | None,
    base: str,
    unit_id: str,
    store: UnitStore,
    agent: Callable[[str], None],
    returns: int,
) -> GuardedStep:
    """Run `agent` in the step: first with an empty reason, then with the guard's reason each
    time the guard fails, up to `returns` times (the caller takes it from the configured
    limit). When the agent raises, the branch is put back before the error goes up. The stored
    request is cleared when the step ends, passed, failed or raised."""
    started = git_out(tree, "rev-parse", "HEAD")
    branch = _current_branch(tree)
    returned = 0
    reason = ""
    try:
        while True:
            try:
                agent(reason)
            except BaseException:
                if request is not None:
                    put_back(tree, branch=branch, started_at=started)
                raise
            verdict = guard_rewrite(
                tree,
                request=request,
                base=base,
                started_at=started,
                unit_id=unit_id,
                branch=branch,
            )
            if verdict.ok or returned >= returns:
                if (
                    verdict.ok
                    and request is not None
                    and git_out(tree, "rev-parse", "HEAD") != started
                ):
                    store.record_event(
                        unit_id,
                        "history_rewritten",
                        f"the unit's commits were rewritten at the request of "
                        f"{request.source.value}",
                        source=request.source.value,
                    )
                return GuardedStep(ok=verdict.ok, returned=returned, verdict=verdict)
            returned += 1
            reason = verdict.reason
    finally:
        store.clear_rewrite_request(unit_id)
