"""Whether a merged pull request's commit reached the repository's default branch."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.shell import git


class Landing(Frozen):
    """Where a merged pull request went: its base, the default branch, and whether its commit
    is on the default branch."""

    base: str
    default_branch: str
    on_default: bool


def merged_on_branch(repo: Path, merge_sha: str, branch: str) -> bool:
    """True when `merge_sha` is an ancestor of `branch` on the remote, after a fetch. A branch
    the remote no longer has is read from the last remote-tracking ref, if there is one."""
    git(repo, "fetch", "-q", "origin", branch, check=False)
    found = git(
        repo,
        "merge-base",
        "--is-ancestor",
        merge_sha,
        f"refs/remotes/origin/{branch}",
        check=False,
    )
    return found.returncode == 0


def merged_on_default(repo: Path, merge_sha: str, default_branch: str) -> bool:
    """True when `merge_sha` is an ancestor of the default branch on the remote, after a fetch."""
    return merged_on_branch(repo, merge_sha, default_branch)


def content_on_default(repo: Path, merge_sha: str, default_branch: str) -> bool:
    """True when every change `merge_sha` made (its diff against its first parent) is already
    applied on the default branch on the remote, after a fetch. It is applied when merging the
    commit into the default branch, with its first parent as the base, changes nothing."""
    git(repo, "fetch", "-q", "origin", default_branch, check=False)
    head = f"refs/remotes/origin/{default_branch}"
    merged = git(
        repo,
        "merge-tree",
        "--write-tree",
        f"--merge-base={merge_sha}^1",
        head,
        merge_sha,
        check=False,
    )
    current = git(repo, "rev-parse", f"{head}^{{tree}}", check=False)
    if merged.returncode != 0 or current.returncode != 0 or not merged.stdout.strip():
        return False
    return merged.stdout.splitlines()[0].strip() == current.stdout.strip()


def default_head(repo: Path, default_branch: str) -> str:
    """The commit the default branch is at on the remote, as of the last fetch."""
    return git(repo, "rev-parse", f"refs/remotes/origin/{default_branch}").stdout.strip()
