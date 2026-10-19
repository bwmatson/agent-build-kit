"""Whether a merged unit was reverted, read from its repository's trunk."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.forges.base import RepoId


def reverts_merge(checkout: Path, *, trunk: str, merge_commit: str, repo: RepoId, pr: int) -> bool:
    """Whether a commit reachable from `trunk`, after `merge_commit`, carries a message line
    `This reverts commit <full sha>` naming it, or `Reverts <owner>/<repo>#<pr>` naming the
    unit's pull request."""
    raise NotImplementedError
