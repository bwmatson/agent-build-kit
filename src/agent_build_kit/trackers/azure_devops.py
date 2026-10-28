"""Azure DevOps work items as a tracker, over the forge's transport."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import httpx

from agent_build_kit.trackers.base import Item, ItemKind
from agent_build_kit.trackers.config import AzureDevOpsTracker


class AzureDevOpsWorkItems:
    def __init__(self, section: AzureDevOpsTracker, *, http: httpx.BaseTransport | None = None):
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
