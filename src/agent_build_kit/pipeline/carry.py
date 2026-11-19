"""Carry a unit that landed off the default branch onto it."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from contextlib import nullcontext
from pathlib import Path

from agent_build_kit.config import RepoConfig
from agent_build_kit.forges import Forge, RepoId
from agent_build_kit.pipeline import shell
from agent_build_kit.pipeline.restack import (
    ConflictContext,
    Resolver,
    RestackConflict,
    Turn,
    ask_resolver,
    conflict_prompt,
    git,
    has_staged_changes,
    push_with_lease,
    read_conflict,
    remote_head,
    take_generated_from_base,
)
from agent_build_kit.pipeline.unit_store import Cause, Pull, StoredUnit, UnitStore
from agent_build_kit.pipeline.units import IN_REVIEW
from agent_build_kit.pipeline.workspaces import worktree_path

CARRY_ROLE = "carry"
CARRY_REFUSED = "carry_refused"

CARRY_NOTE = """
This is a cherry-pick onto the default branch, not a rebase. If it cannot be resolved the carry
is abandoned and the unit stays held for a person.
"""


def carry_branch(unit_id: str) -> str:
    """The branch a unit's carry is made on."""
    return f"spec/{unit_id}/carry"


def is_carrying(unit: StoredUnit) -> bool:
    """Whether the unit has a pull request that carries it already."""
    return any(pull.role == CARRY_ROLE for pull in unit.pulls)


def carry(
    store: UnitStore,
    unit_id: str,
    *,
    forge: Forge,
    repo_id: RepoId,
    repo: Path,
    default_branch: str,
    worktrees: Path,
    on_empty: Callable[[StoredUnit, str], None],
    resolve: Resolver | None = None,
    repo_config: RepoConfig | None = None,
    turn: Turn = nullcontext,
) -> None:
    """Cherry-pick the unit's merge commit onto `spec/<unit>/carry`, a branch off the default
    branch (as the remote has it, after a fetch) made in a worktree under `worktrees`, and open
    a pull request against the default branch, recorded as role `carry`. The unit is `in_review`
    with cause `carried`; one that already carries is left alone. A cherry-pick that leaves
    nothing to commit opens no pull request: `on_empty` is given the unit and the default
    branch's head, and records the unit merged as the landing re-check records a squash.

    It can be run again after a failure: the branch is pushed with a lease on what the remote
    holds for it, a pull request the forge already has for it is reused, and a worktree left
    by a run that was killed is cleared first.

    A conflict is resolved as a restack's is (`ask_resolver`: both sides' intent, generated
    files from the base, the answer checked). One that cannot be resolved aborts the cherry-pick
    and raises `RestackConflict`, with no pull request opened and the unit as it was."""
    unit = store.get(unit_id)
    if is_carrying(unit):
        return
    sha = unit.merge_sha or next(
        (pull.merge_sha for pull in reversed(unit.pulls) if pull.merge_sha), None
    )
    if sha is None:
        raise ValueError(f"{unit_id}: no commit recorded to carry")
    branch = carry_branch(unit_id)
    path = worktree_path(repo, branch, worktrees, name=unit.repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    start = default_branch
    with turn():
        if shell.has_origin(repo):
            git(repo, "fetch", "-q", "origin", default_branch, check=False)
            start = f"refs/remotes/origin/{default_branch}"
        if path.exists():
            # Left by a run that was killed mid-carry: cleared first, as a restack's tree is.
            git(path, "cherry-pick", "--abort", check=False)
            git(repo, "worktree", "remove", "--force", str(path), check=False)
        git(repo, "worktree", "prune", check=False)
        git(repo, "worktree", "add", "-q", "-B", branch, str(path), start)
    try:
        context = ConflictContext(
            moving_unit=unit_id,
            moving_intent=f"{unit.title} (already merged into another branch, carried here)",
            onto_unit=default_branch,
            onto_intent="the default branch as it stands",
            moving_change=unit.change,
            moving_repo=unit.repo,
            repo=repo_config,
        )
        if not _pick(path, sha, resolve, context, repo_config, turn):
            # Nothing to carry: the default branch's head stands for the merge.
            on_empty(unit, git(repo, "rev-parse", start).stdout.strip())
            return
        with turn():
            # A retry makes the branch again, with a new commit: lease against what the
            # remote holds for it now, so the push is not refused as non-fast-forward.
            held = remote_head(path, branch)
            if held is None:
                raise RuntimeError(f"could not ask the remote for {branch}")
            push_with_lease(path, branch, last_pushed=held or None)
    finally:
        with turn():
            git(repo, "worktree", "remove", "--force", str(path), check=False)
    # One pull request however many rounds it took: one opened before a failure is reused.
    number = forge.find_pr(repo_id, head=branch)
    if number is None:
        first = next((pull.number for pull in unit.pulls if pull.role != CARRY_ROLE), unit.pr)
        number = forge.create_pr(
            repo_id,
            head=branch,
            base=default_branch,
            title=f"Carry {unit_id} onto {default_branch}",
            body=(
                f"{unit_id} was merged into a branch other than {default_branch}"
                + (f" (#{first})" if first else "")
                + "; this carries its work onto it."
            ),
        )
    store.set_pulls(unit_id, (*unit.pulls, Pull(number=number, branch=branch, role=CARRY_ROLE)))
    store.set_merge_record(unit_id, None, None)
    store.set_state(
        unit_id,
        IN_REVIEW,
        pr=number,
        branch=branch,
        note=f"carrying onto {default_branch}",
        cause=Cause.CARRIED,
    )


def _pick_stopped(path: Path) -> bool:
    return git(path, "rev-parse", "-q", "--verify", "CHERRY_PICK_HEAD", check=False).returncode == 0


def _pick(
    path: Path,
    sha: str,
    resolve: Resolver | None,
    context: ConflictContext,
    repo_config: RepoConfig | None,
    turn: Turn,
) -> bool:
    """Cherry-pick `sha` in `path`; False when it leaves nothing to commit. A merge commit is
    picked against its first parent."""
    parents = git(path, "rev-list", "--parents", "-n", "1", sha).stdout.split()[1:]
    args = ["cherry-pick", *(["-m", "1"] if len(parents) > 1 else []), sha]
    with turn():
        result = git(path, *args, check=False)
    if result.returncode == 0:
        return True

    def abort(message: str, tried: str = "") -> RestackConflict:
        git(path, "cherry-pick", "--abort", check=False)
        return RestackConflict(message, tried=tried)

    def fail() -> subprocess.CalledProcessError:
        git(path, "cherry-pick", "--abort", check=False)
        return subprocess.CalledProcessError(result.returncode, args, result.stdout, result.stderr)

    if not _pick_stopped(path):
        raise fail()
    patterns = repo_config.generated_paths() if repo_config else ()
    with turn():
        settled, others = take_generated_from_base(path, patterns)
        if not others:
            if has_staged_changes(path):
                git(path, "-c", "core.editor=true", "cherry-pick", "--continue")
                return True
            # Stopped as empty: the base already holds what the commit changed.
            git(path, "cherry-pick", "--abort", check=False)
            return False
    if resolve is None:
        with turn():
            raise abort(f"cherry-pick of {sha} conflicts in {', '.join(others)}")
    with turn():
        conflict = read_conflict(
            path,
            result.stdout + result.stderr,
            branch=sha,
            old_base=f"{sha}^1",
            must_keep=None,
            started=sha,
        )
        prompt = conflict_prompt(path, conflict, context, settled) + CARRY_NOTE
    ask_resolver(
        path,
        prompt,
        conflict,
        resolve=resolve,
        context=context,
        turn=turn,
        stop=lambda: git(path, "cherry-pick", "--abort", check=False),
        give_up=abort,
        label=sha,
    )
    with turn():
        # What the conflict touched, and what was already tracked; a stray new file is left out.
        git(path, "add", "-u")
        git(path, "add", "--", *conflict.files)
        finished = git(path, "-c", "core.editor=true", "cherry-pick", "--continue", check=False)
        if finished.returncode != 0:
            raise abort(
                f"the cherry-pick did not complete after resolution:\n"
                f"{finished.stdout}\n{finished.stderr}"
            )
    return True
