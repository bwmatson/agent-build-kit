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
) -> GuardVerdict:
    """Check the branch checked out in `tree` after a step that started at `started_at` with
    `request`; `base` is where the unit's own commits begin. A step with no request is not
    checked. A failure moves the branch back to `started_at`."""
    if request is None:
        return GuardVerdict(ok=True)
    head = git_out(tree, "rev-parse", "HEAD")
    if head == started_at:
        return GuardVerdict(ok=True)
    origin = git_out(tree, "merge-base", base, started_at)
    verdict = _check(tree, origin=origin, base=base, head=head, unit_id=unit_id)
    if not verdict.ok:
        git(tree, "reset", "-q", "--hard", started_at)
    return verdict


def _check(tree: Path, *, origin: str, base: str, head: str, unit_id: str) -> GuardVerdict:
    """The verdict on the commits between `origin`, where the unit began, and `head`."""
    chain = git_out(tree, "rev-list", "--reverse", "--first-parent", f"{origin}..{head}").split()
    moved_in = (
        git_out(tree, "rev-parse", base) != origin
        and git(tree, "merge-base", "--is-ancestor", base, head, check=False).returncode == 0
    )
    if moved_in or (chain and git_out(tree, "rev-parse", f"{chain[0]}^") != origin):
        return GuardVerdict(
            ok=False,
            check=GuardCheck.BASE,
            reason=f"the unit's base {base} ({origin}) is no longer where the unit's commits "
            "begin; rewrite only the unit's own commits above it",
        )
    commits = git_out(tree, "rev-list", "--reverse", f"{origin}..{head}").split()
    merges = [
        c for c in commits if len(git_out(tree, "rev-list", "--parents", "-n1", c).split()) > 2
    ]
    if merges:
        return GuardVerdict(
            ok=False,
            check=GuardCheck.MERGE,
            reason="merge commits above the base are not allowed: " + ", ".join(merges),
        )
    trailer = f"Unit: {unit_id}"
    missing = [
        c
        for c in commits
        if trailer not in git_out(tree, "show", "-s", "--format=%B", c).splitlines()
    ]
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
    returns: int | None,
) -> GuardedStep:
    """Run `agent` in the step: first with an empty reason, then with the guard's reason each
    time the guard fails, up to `returns` times (None: no limit). The stored request is cleared
    when the step ends, passed or failed."""
    started = git_out(tree, "rev-parse", "HEAD")
    returned = 0
    reason = ""
    try:
        while True:
            agent(reason)
            verdict = guard_rewrite(
                tree, request=request, base=base, started_at=started, unit_id=unit_id
            )
            if verdict.ok or (returns is not None and returned >= returns):
                return GuardedStep(ok=verdict.ok, returned=returned, verdict=verdict)
            returned += 1
            reason = verdict.reason
    finally:
        store.clear_rewrite_request(unit_id)
