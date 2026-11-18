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
    applied on the default branch on the remote, after a fetch."""
    raise NotImplementedError
