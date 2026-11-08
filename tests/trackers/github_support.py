"""Configurations of the owner kinds the GitHub issues tracker tests run against."""

from __future__ import annotations

from typing import Any

from agent_build_kit.trackers.config import GithubTracker
from agent_build_kit.trackers.github import GithubIssues
from tests.trackers.github_issue_host import IssueHost

# Owner mode -> the issue type (organization) or label (user) of each level.
MODE_TYPES: dict[str, dict[str, str]] = {
    "organization": {"change": "Feature", "group": "Story", "task": "Task"},
    "user": {"change": "abk:change", "group": "abk:group", "task": "abk:task"},
}


def section(mode: str = "organization", **overrides: Any) -> GithubTracker:
    """The configuration of an owner mode; `overrides` set fields of the `github` block."""
    made = GithubTracker(
        kind="github",
        owner="example",
        repo="app",
        levels=("change", "group", "task"),
        types=MODE_TYPES[mode],
    )
    return made.model_copy(update=overrides)


def tracker_on(host: IssueHost, mode: str = "organization", **overrides: Any) -> GithubIssues:
    """The tracker of an owner mode, talking to the in-memory host."""
    return GithubIssues(section(mode, **overrides), http=host)
