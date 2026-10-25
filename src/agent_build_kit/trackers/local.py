"""The in-memory stand-in tracker, with configurable capabilities."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from agent_build_kit.trackers.base import (
    Capabilities,
    Change,
    Cursor,
    Identity,
    Item,
    ItemKind,
    Relation,
)


class LocalTracker:
    def __init__(self, capabilities: Capabilities | None = None, who: str = "sync") -> None:
        raise NotImplementedError

    def capabilities(self) -> Capabilities:
        raise NotImplementedError

    def identity(self) -> Identity:
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

    def update(
        self, item_id: str, changes: Mapping[str, str], expected_revision: str | None = None
    ) -> Item:
        raise NotImplementedError

    def children(self, item_id: str) -> Sequence[Item]:
        raise NotImplementedError

    def set_assignee(self, item_id: str, who: str, expected_revision: str | None = None) -> Item:
        raise NotImplementedError

    def claim(self, item_id: str) -> bool:
        raise NotImplementedError

    def link(self, item_id: str, relation: str, target_id: str) -> Relation:
        raise NotImplementedError

    def comment(self, item_id: str, text: str) -> None:
        raise NotImplementedError

    def changed_since(self, cursor: Cursor | None) -> tuple[Sequence[Change], Cursor]:
        raise NotImplementedError

    def find_by_marker(self, marker: str) -> Item | None:
        raise NotImplementedError
