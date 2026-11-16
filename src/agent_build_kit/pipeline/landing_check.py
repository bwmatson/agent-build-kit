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


def merged_on_default(repo: Path, merge_sha: str, default_branch: str) -> bool:
    """True when `merge_sha` is an ancestor of the default branch on the remote, after a fetch."""
    git(repo, "fetch", "-q", "origin", default_branch, check=False)
    found = git(
        repo,
        "merge-base",
        "--is-ancestor",
        merge_sha,
        f"refs/remotes/origin/{default_branch}",
        check=False,
    )
    return found.returncode == 0
