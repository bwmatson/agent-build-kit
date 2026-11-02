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
    StaleRevision,
    split_tags,
    with_status_tags,
)
from agent_build_kit.trackers.manual_parent import ManualParent

# The board type the stand-in gives an item a person made as the manual parent.
EPIC_TYPE = "epic"

# The fields `update` accepts, as on every tracker.
UPDATABLE = frozenset({"title", "body", "state", "tags"})


class LocalTracker:
    def __init__(
        self,
        capabilities: Capabilities | None = None,
        who: str = "sync",
        levels: Sequence[ItemKind] | None = None,
    ) -> None:
        self._levels = tuple(levels) if levels is not None else None
        self._capabilities = capabilities or Capabilities()
        self._who = who
        self._items: dict[str, Item] = {}
        self._log: list[Change] = []
        self._comments: dict[str, list[str]] = {}
        self._relations: list[Relation] = []
        self._epics: set[str] = set()

    def as_identity(self, who: str) -> LocalTracker:
        """A view of the same items acting as another identity: the competing writer."""
        view = LocalTracker(self._capabilities, who, self._levels)
        view._items = self._items
        view._log = self._log
        view._comments = self._comments
        view._relations = self._relations
        view._epics = self._epics
        return view

    def add_epic(self, title: str) -> Item:
        """A manual epic: the read-only parent of the first level, made by a person."""
        item = self._add("change", title, "", None, ())
        self._epics.add(item.id)
        return item

    def read_manual_parent(self, item_id: str) -> ManualParent | None:
        item = self._items.get(item_id)
        return None if item is None else self._as_manual_parent(item)

    def find_manual_parents(self, title: str) -> Sequence[ManualParent]:
        """A loose search, as a board's is: any item whose title holds the text, in any case."""
        return [
            self._as_manual_parent(item)
            for item in self._items.values()
            if title.lower() in item.title.lower()
        ]

    def _as_manual_parent(self, item: Item) -> ManualParent:
        type_ = EPIC_TYPE if item.id in self._epics else item.kind
        return ManualParent(id=item.id, title=item.title, type=type_)

    def capabilities(self) -> Capabilities:
        return self._capabilities

    def identity(self) -> Identity:
        return Identity(name=self._who)

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
        if self._levels is not None and kind not in self._levels:
            raise ValueError(f"kind {kind!r} is not one of the levels in use: {list(self._levels)}")
        return self._add(kind, title, body, parent, markers)

    def _add(
        self, kind: ItemKind, title: str, body: str, parent: str | None, markers: Sequence[str]
    ) -> Item:
        item_id = str(len(self._items) + 1)
        item = Item(
            id=item_id,
            kind=kind,
            title=title,
            body=body,
            state=self._capabilities.states[0],
            assignees=(),
            parent_id=parent,
            revision="1",
            url=f"local://items/{item_id}",
            markers=tuple(markers),
        )
        self._items[item_id] = item
        self._record(item, ("created",))
        return item

    def get(self, item_id: str) -> Item:
        return self._items[item_id]

    def update(
        self, item_id: str, changes: Mapping[str, str], expected_revision: str | None = None
    ) -> Item:
        unknown = sorted(set(changes) - UPDATABLE)
        if unknown:
            raise ValueError(f"cannot update {unknown} of an item")
        self._check_revision(self._items[item_id], expected_revision)
        values: dict[str, object] = dict(changes)
        if "tags" in changes:
            values["tags"] = with_status_tags(
                self._items[item_id].tags, split_tags(changes["tags"])
            )
        return self._change(item_id, **values)

    def children(self, item_id: str) -> Sequence[Item]:
        return [item for item in self._items.values() if item.parent_id == item_id]

    def set_assignee(self, item_id: str, who: str, expected_revision: str | None = None) -> Item:
        self._check_revision(self._items[item_id], expected_revision)
        return self._change(item_id, assignees=(who,) if who else ())

    def claim(self, item_id: str) -> bool:
        if not self._items[item_id].assignees:
            self._change(item_id, assignees=(self._who,))
        # Without a revision check the write may have been overwritten: report what is there.
        return self._items[item_id].assignees == (self._who,)

    def link(self, item_id: str, relation: str, target_id: str) -> Relation:
        link = Relation(kind=relation, source_id=item_id, target_id=target_id)
        if link not in self._relations:
            self._relations.append(link)
        return link

    def comment(self, item_id: str, text: str) -> None:
        self._comments.setdefault(item_id, []).append(text)

    def changed_since(self, cursor: Cursor | None) -> tuple[Sequence[Change], Cursor]:
        start = int(cursor.value) if cursor else 0
        return self._log[start:], Cursor(value=str(len(self._log)))

    def find_by_marker(self, marker: str) -> Item | None:
        return next((item for item in self._items.values() if marker in item.markers), None)

    def _check_revision(self, item: Item, expected: str | None) -> None:
        if self._capabilities.revision_check and expected is not None and expected != item.revision:
            raise StaleRevision(f"item {item.id} is at revision {item.revision}, not {expected}")

    def _change(self, item_id: str, **changes: object) -> Item:
        current = self._items[item_id]
        item = current.model_copy(update={**changes, "revision": str(int(current.revision) + 1)})
        self._items[item_id] = item
        self._record(item, tuple(changes))
        return item

    def _record(self, item: Item, fields: tuple[str, ...]) -> None:
        self._log.append(
            Change(
                item_id=item.id,
                revision=item.revision,
                fields=fields,
                who=self._who,
                when=str(len(self._log)),
            )
        )
