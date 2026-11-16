"""Whether a merged pull request's commit reached the repository's default branch."""

from __future__ import annotations

from pathlib import Path


def merged_on_default(repo: Path, merge_sha: str, default_branch: str) -> bool:
    """True when `merge_sha` is an ancestor of the default branch on the remote, after a fetch."""
    raise NotImplementedError
