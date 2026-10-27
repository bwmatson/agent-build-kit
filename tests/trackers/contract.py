"""The contract every tracker implementation is run against.

An implementation's tests build a `Shape` with `shape_of` for each board shape (the levels in
use, with or without a manual epic above the first one) and run each scenario in `SCENARIOS`
against it. A scenario skips, with a stated reason, what a missing capability rules out.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any, cast

import pytest

from agent_build_kit.trackers.base import Item, ItemKind, StaleRevision, Tracker

# The kit's levels, by the kind the protocol names them today.
LEVEL_KINDS: dict[str, ItemKind] = {"change": "feature", "group": "story", "task": "task"}
LEVEL_SETS: dict[str, tuple[str, ...]] = {
    "change": ("change",),
    "change-group": ("change", "group"),
    "change-group-task": ("change", "group", "task"),
}
WRITES = ("update", "set_assignee", "claim", "comment", "link")


class Watched:
    """A tracker that notes every write aimed at the manual epic, which only ever receives reads."""

    def __init__(self, inner: Tracker, epic_id: str | None, epic_writes: list[str]) -> None:
        self._inner = inner
        self._epic_id = epic_id
        self._epic_writes = epic_writes

    @staticmethod
    def _items_named(name: str, args: tuple[Any, ...], kwargs: dict[str, Any]) -> list[Any]:
        """The items a write is aimed at: its subject, and a link's target. Not a revision."""
        subject = args[0] if args else kwargs.get("item_id")
        target = args[2] if len(args) > 2 else kwargs.get("target_id")
        return [subject, target] if name == "link" else [subject]

    def __getattr__(self, name: str) -> Any:
        attribute = getattr(self._inner, name)
        if name not in WRITES:
            return attribute

        def call(*args: Any, **kwargs: Any) -> Any:
            if self._epic_id in self._items_named(name, args, kwargs):
                self._epic_writes.append(name)
            return attribute(*args, **kwargs)

        return call


class Shape:
    """A board to test: the tracker, a competing identity on it, its levels and its epic."""

    def __init__(
        self,
        tracker: Tracker,
        competitor: Tracker,
        levels: Sequence[str],
        epic: Item | None,
    ) -> None:
        self.epic = epic
        self.epic_writes: list[str] = []
        epic_id = epic.id if epic else None
        self.tracker = cast(Tracker, Watched(tracker, epic_id, self.epic_writes))
        self.competitor = cast(Tracker, Watched(competitor, epic_id, self.epic_writes))
        self.kinds = [LEVEL_KINDS[level] for level in levels]

    def top(self, title: str = "Top") -> Item:
        """An item of the first level, under the epic when there is one."""
        return self.tracker.create(self.kinds[0], title, parent=self.epic.id if self.epic else None)


def shape_of(
    tracker: Tracker, competitor: Tracker, levels: Sequence[str], epic: Item | None = None
) -> Shape:
    return Shape(tracker, competitor, levels, epic)


def create_each_level_under_its_parent(shape: Shape) -> None:
    parent = shape.epic.id if shape.epic else None
    made: list[Item] = []
    for kind in shape.kinds:
        item = shape.tracker.create(kind, f"{kind} item", f"{kind} body", parent)
        assert isinstance(item.id, str) and item.id
        assert (item.kind, item.title, item.body, item.parent_id) == (
            kind,
            f"{kind} item",
            f"{kind} body",
            parent,
        )
        assert shape.tracker.get(item.id) == item
        made.append(item)
        parent = item.id
    for above, below in zip(made, made[1:], strict=False):
        assert [child.id for child in shape.tracker.children(above.id)] == [below.id]
    if shape.epic:
        assert made[0].id in [child.id for child in shape.tracker.children(shape.epic.id)]


def update_conditionally(shape: Shape) -> None:
    if not shape.tracker.capabilities().revision_check:
        pytest.skip("the tracker has no revision check, so a stale update cannot be refused")
    item = shape.top()
    shape.competitor.update(item.id, {"title": "Theirs"})
    theirs = shape.tracker.get(item.id)

    with pytest.raises(StaleRevision):
        shape.tracker.update(item.id, {"title": "Mine"}, expected_revision=item.revision)

    assert shape.tracker.get(item.id) == theirs
    updated = shape.tracker.update(item.id, {"title": "Mine"}, expected_revision=theirs.revision)
    assert (updated.title, shape.tracker.get(item.id).title) == ("Mine", "Mine")


def assign_and_claim_with_a_competitor(shape: Shape) -> None:
    item = shape.top()
    assert shape.tracker.claim(item.id) is True
    assert shape.tracker.get(item.id).assignees == (shape.tracker.identity().name,)

    taken = shape.top("Taken")
    assert shape.competitor.claim(taken.id) is True
    assert shape.tracker.claim(taken.id) is False
    assert shape.tracker.get(taken.id).assignees == (shape.competitor.identity().name,)


def assign_someone_else(shape: Shape) -> None:
    if not shape.tracker.capabilities().assign_others:
        pytest.skip("the tracker cannot assign other people")
    item = shape.top()

    assigned = shape.tracker.set_assignee(item.id, "someone")

    assert assigned.assignees == ("someone",)
    assert shape.tracker.get(item.id).assignees == ("someone",)


def comment(shape: Shape) -> None:
    """Only that the call is accepted: the protocol has no way to read a comment back."""
    if not shape.tracker.capabilities().comment:
        pytest.skip("the tracker cannot hold comments")
    shape.tracker.comment(shape.top().id, "a note")


def link(shape: Shape) -> None:
    first, second = shape.top("First"), shape.top("Second")

    relation = shape.tracker.link(first.id, "blocks", second.id)

    assert (relation.kind, relation.source_id, relation.target_id) == (
        "blocks",
        first.id,
        second.id,
    )


def changes_since_a_cursor_made_by_another_identity(shape: Shape) -> None:
    item = shape.top()
    _, cursor = shape.tracker.changed_since(None)

    shape.competitor.update(item.id, {"body": "edited"})

    changes, _ = shape.tracker.changed_since(cursor)
    assert [(change.item_id, change.who) for change in changes] == [
        (item.id, shape.competitor.identity().name)
    ]
    assert "body" in changes[0].fields


def find_by_marker_is_stable(shape: Shape) -> None:
    parent = shape.epic.id if shape.epic else None
    shape.tracker.create(shape.kinds[0], "Lost", parent=parent, markers=("abk:lost",))

    found = shape.tracker.find_by_marker("abk:lost")

    assert found is not None and found.title == "Lost"
    assert shape.tracker.find_by_marker("abk:never-made") is None
    again = shape.tracker.find_by_marker("abk:lost")
    assert again is not None and again.id == found.id


def the_epic_only_receives_reads(shape: Shape) -> None:
    if shape.epic is None:
        pytest.skip("the board has no manual epic")
    item = shape.top()
    shape.tracker.claim(item.id)
    shape.tracker.comment(item.id, "a note")

    assert shape.tracker.get(shape.epic.id) == shape.epic
    assert shape.epic_writes == []


SCENARIOS: dict[str, Callable[[Shape], None]] = {
    function.__name__: function
    for function in (
        create_each_level_under_its_parent,
        update_conditionally,
        assign_and_claim_with_a_competitor,
        assign_someone_else,
        comment,
        link,
        changes_since_a_cursor_made_by_another_identity,
        find_by_marker_is_stable,
        the_epic_only_receives_reads,
    )
}
