"""What a work tracker has to answer, and the values it answers with.

Like the forge, a tracker returns typed values and never the host's own documents, and it
is a `Protocol` so an implementation owns its code. Ids are strings so issue numbers and
node ids both fit.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Literal, Protocol

from agent_build_kit.model import Frozen

ItemKind = Literal["feature", "story", "task"]


class Identity(Frozen):
    """Who the tracker's credential is."""

    name: str


class Cursor(Frozen):
    """Where a `changed_since` listing stopped; opaque to callers."""

    value: str


class Capabilities(Frozen):
    """What a tracker really does, so code above it never asks which tracker it is."""

    hierarchy: Literal["native", "label"] = "native"
    typed: bool = True
    revision_check: bool = True
    assign_others: bool = True
    states: tuple[str, ...] = ("new", "active", "done")
    comment: bool = True


class Item(Frozen):
    id: str
    kind: ItemKind
    title: str
    body: str
    state: str
    assignees: tuple[str, ...]
    parent_id: str | None
    revision: str
    url: str
    markers: tuple[str, ...] = ()


class Relation(Frozen):
    kind: str
    source_id: str
    target_id: str


class Change(Frozen):
    item_id: str
    revision: str
    fields: tuple[str, ...]
    who: str
    when: str


class StaleRevision(RuntimeError):
    """An update refused because the item changed since the revision given."""


class Tracker(Protocol):
    def capabilities(self) -> Capabilities: ...

    def identity(self) -> Identity: ...

    def create(
        self,
        kind: ItemKind,
        title: str,
        body: str = "",
        parent: str | None = None,
        *,
        markers: Sequence[str] = (),
        fields: Mapping[str, str] | None = None,
    ) -> Item: ...

    def get(self, item_id: str) -> Item: ...

    def update(
        self, item_id: str, changes: Mapping[str, str], expected_revision: str | None = None
    ) -> Item: ...

    def children(self, item_id: str) -> Sequence[Item]: ...

    def set_assignee(
        self, item_id: str, who: str, expected_revision: str | None = None
    ) -> Item: ...

    def claim(self, item_id: str) -> bool: ...

    def link(self, item_id: str, relation: str, target_id: str) -> Relation: ...

    def comment(self, item_id: str, text: str) -> None: ...

    def changed_since(self, cursor: Cursor | None) -> tuple[Sequence[Change], Cursor]: ...

    def find_by_marker(self, marker: str) -> Item | None: ...
