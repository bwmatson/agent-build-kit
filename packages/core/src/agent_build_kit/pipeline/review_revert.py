"""Whether a merged unit was reverted, read from its repository's trunk."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from agent_build_kit.forges.base import RepoId
from agent_build_kit.pipeline.shell import git


def reverts_pull_request(
    checkout: Path, *, trunk: str, repo: RepoId, pr: int, since: datetime, until: datetime
) -> bool | None:
    """Whether the trunk, from `since` to `until`, reverts the pull request `pr`, found by its
    merge commit's subject or by the line `Reverts <owner>/<repo>#<pr>`; None when the
    checkout could not be searched."""
    window = ("--since", since.isoformat(), "--until", until.isoformat())
    subjects = git(checkout, "log", *window, "--format=%H%x09%s", trunk, check=False)
    if subjects.returncode:
        return None
    ended = rf"\(#{pr}\)$|^Merged PR {pr}:"
    for line in subjects.stdout.splitlines():
        sha, _, subject = line.partition("\t")
        if re.search(ended, subject):
            return reverts_merge(
                checkout, trunk=trunk, merge_commit=sha, repo=repo, pr=pr, until=until
            )
    log = git(checkout, "log", *window, "--format=%B%x00", trunk, check=False)
    if log.returncode:
        return None
    pulled = rf"^Reverts {re.escape(repo.account)}/{re.escape(repo.name)}#{pr}(?!\d)"
    return re.search(pulled, log.stdout, re.MULTILINE) is not None


def reverts_merge(
    checkout: Path,
    *,
    trunk: str,
    merge_commit: str,
    repo: RepoId,
    pr: int,
    until: datetime | None = None,
) -> bool | None:
    """Whether a commit reachable from `trunk`, after `merge_commit`, carries a message line
    `This reverts commit <full sha>` naming it, or `Reverts <owner>/<repo>#<pr>` naming the
    unit's pull request. None when the checkout could not be searched (it does not hold the
    merge commit or the trunk), which is not the same as a search that found nothing."""
    bound = ("--until", until.isoformat()) if until is not None else ()
    log = git(checkout, "log", *bound, "--format=%B%x00", f"{merge_commit}..{trunk}", check=False)
    if log.returncode:
        return None  # nothing was searched, so no revert has been ruled out
    messages = log.stdout
    named = rf"^This reverts commit {re.escape(merge_commit)}(?![0-9a-fA-F])"
    pulled = rf"^Reverts {re.escape(repo.account)}/{re.escape(repo.name)}#{pr}(?!\d)"
    return any(re.search(pattern, messages, re.MULTILINE) for pattern in (named, pulled))
