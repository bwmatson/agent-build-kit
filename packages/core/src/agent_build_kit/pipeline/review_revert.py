"""Whether a merged unit was reverted, read from its repository's trunk."""

from __future__ import annotations

import re
from pathlib import Path

from agent_build_kit.forges.base import RepoId
from agent_build_kit.pipeline.shell import git


def reverts_merge(
    checkout: Path, *, trunk: str, merge_commit: str, repo: RepoId, pr: int
) -> bool | None:
    """Whether a commit reachable from `trunk`, after `merge_commit`, carries a message line
    `This reverts commit <full sha>` naming it, or `Reverts <owner>/<repo>#<pr>` naming the
    unit's pull request. None when the checkout could not be searched (it does not hold the
    merge commit or the trunk), which is not the same as a search that found nothing."""
    log = git(checkout, "log", "--format=%B%x00", f"{merge_commit}..{trunk}", check=False)
    if log.returncode:
        return None  # nothing was searched, so no revert has been ruled out
    messages = log.stdout
    named = rf"^This reverts commit {re.escape(merge_commit)}(?![0-9a-fA-F])"
    pulled = rf"^Reverts {re.escape(repo.account)}/{re.escape(repo.name)}#{pr}(?!\d)"
    return any(re.search(pattern, messages, re.MULTILINE) for pattern in (named, pulled))
