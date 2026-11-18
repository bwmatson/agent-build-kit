"""Carry a unit that landed off the default branch onto it."""

from __future__ import annotations

import subprocess
from pathlib import Path

from agent_build_kit.forges import Forge, RepoId
from agent_build_kit.pipeline.restack import Resolver, conflicted_files, git, push_with_lease
from agent_build_kit.pipeline.unit_store import Cause, Pull, UnitStore
from agent_build_kit.pipeline.units import IN_REVIEW, MERGED
from agent_build_kit.pipeline.workspaces import worktree_key

CARRY_ROLE = "carry"


def carry_branch(unit_id: str) -> str:
    """The branch a unit's carry is made on."""
    return f"spec/{unit_id}/carry"


def carry(
    store: UnitStore,
    unit_id: str,
    *,
    forge: Forge,
    repo_id: RepoId,
    repo: Path,
    default_branch: str,
    worktrees: Path,
    resolve: Resolver | None = None,
) -> None:
    """Cherry-pick the unit's merge commit onto `spec/<unit>/carry`, a branch off the default
    branch made in a worktree under `worktrees`, and open a pull request against the default
    branch, recorded as role `carry`. The unit is `in_review` with cause `carried`; one that
    already carries is left alone, and a cherry-pick that leaves nothing to commit opens no pull
    request and records the unit `merged`."""
    unit = store.get(unit_id)
    if any(pull.role == CARRY_ROLE for pull in unit.pulls):
        return
    sha = unit.merge_sha or next(
        (pull.merge_sha for pull in reversed(unit.pulls) if pull.merge_sha), None
    )
    if sha is None:
        raise ValueError(f"{unit_id}: no commit recorded to carry")
    branch = carry_branch(unit_id)
    path = worktrees / worktree_key(unit_id) / "carry"
    path.parent.mkdir(parents=True, exist_ok=True)
    git(repo, "worktree", "prune", check=False)
    git(repo, "worktree", "add", "-q", "-B", branch, str(path), default_branch)
    try:
        if not _pick(path, sha, resolve):
            store.set_state(unit_id, MERGED, note=f"its changes are already on {default_branch}")
            return
        push_with_lease(path, branch, last_pushed=None)
    finally:
        git(repo, "worktree", "remove", "--force", str(path), check=False)
    number = forge.create_pr(
        repo_id,
        head=branch,
        base=default_branch,
        title=f"Carry {unit_id} onto {default_branch}",
        body=f"{unit_id} was merged into a branch other than {default_branch}; this carries it.",
    )
    store.set_pulls(unit_id, (*unit.pulls, Pull(number=number, branch=branch, role=CARRY_ROLE)))
    store.set_merge_record(unit_id, None, None)
    store.set_state(
        unit_id,
        IN_REVIEW,
        pr=number,
        branch=branch,
        note=f"carrying {sha[:10]} onto {default_branch}",
        cause=Cause.CARRIED,
    )


def _pick(path: Path, sha: str, resolve: Resolver | None) -> bool:
    """Cherry-pick `sha` in `path`; False when it leaves nothing to commit."""
    parents = git(path, "rev-list", "--parents", "-n", "1", sha).stdout.split()[1:]
    args = ["cherry-pick", *(["-m", "1"] if len(parents) > 1 else []), sha]
    result = git(path, *args, check=False)
    if result.returncode == 0:
        return True
    files = conflicted_files(path)
    if not files:
        nothing_staged = git(path, "diff", "--cached", "--quiet", check=False).returncode == 0
        git(path, "cherry-pick", "--abort", check=False)
        if nothing_staged:
            return False
        raise subprocess.CalledProcessError(result.returncode, args, result.stdout, result.stderr)
    if resolve is None:
        git(path, "cherry-pick", "--abort", check=False)
        raise RuntimeError(f"cherry-pick of {sha} conflicts in {', '.join(files)}")
    resolve(f"Resolve the merge conflicts in these files only: {', '.join(files)}", cwd=path)
    git(path, "add", "-A")
    git(path, "-c", "core.editor=true", "cherry-pick", "--continue")
    return True
