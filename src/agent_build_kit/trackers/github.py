"""GitHub issues as a tracker, over the forge's transport.

Each kit item is an issue carrying the kit's marker; the hierarchy is sub-issues, and a level
is an issue type for an organization with types and a label otherwise.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import httpx

from agent_build_kit.trackers.base import Capabilities, Item, ItemKind
from agent_build_kit.trackers.config import GithubTracker

# The most sub-issues one parent holds.
SUB_ISSUE_LIMIT = 100


class SubIssueLimitExceeded(ValueError):
    """A parent that already holds the most sub-issues the host allows: a configuration problem,
    naming the parent and the limit."""


class GithubIssues:
    def __init__(self, section: GithubTracker, *, http: httpx.BaseTransport | None = None):
        raise NotImplementedError

    def capabilities(self) -> Capabilities:
        raise NotImplementedError

    def create(
        self,
        kind: ItemKind,
        title: str,
        body: str = "",
        parent: str | None = None,
        *,
        markers: Sequence[str] = (),
        fields: Mapping[str, str] | None = None,
    ) -> Item:
        raise NotImplementedError

    def get(self, item_id: str) -> Item:
        raise NotImplementedError

    def children(self, item_id: str) -> Sequence[Item]:
        raise NotImplementedError

    def find_by_marker(self, marker: str) -> Item | None:
        raise NotImplementedError
