"""The manual parent of a change: resolved by reads, checked, and only ever read."""

from __future__ import annotations

from collections.abc import Mapping

import pytest

from agent_build_kit.trackers.base import Item, Relation
from agent_build_kit.trackers.local import LocalTracker
from agent_build_kit.trackers.manual_parent import (
    ManualParentError,
    create_change_item,
    resolve_manual_parent,
)

TITLE = "Agent Assessment: P0 Foundation"


class RecordingTracker(LocalTracker):
    """A local tracker that records every call that writes to or links an item."""

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[tuple[str, str]] = []
        # The items made by hand, which a title lookup can find.
        self.known: list[Item] = []

    def update(
        self, item_id: str, changes: Mapping[str, str], expected_revision: str | None = None
    ) -> Item:
        self.calls.append(("update", item_id))
        return super().update(item_id, changes, expected_revision)

    def set_assignee(self, item_id: str, who: str, expected_revision: str | None = None) -> Item:
        self.calls.append(("set_assignee", item_id))
        return super().set_assignee(item_id, who, expected_revision)

    def claim(self, item_id: str) -> bool:
        self.calls.append(("claim", item_id))
        return super().claim(item_id)

    def comment(self, item_id: str, text: str) -> None:
        self.calls.append(("comment", item_id))
        super().comment(item_id, text)

    def link(self, item_id: str, relation: str, target_id: str) -> Relation:
        self.calls.extend([("link", item_id), ("link", target_id)])
        return super().link(item_id, relation, target_id)

    def written(self, item_id: str) -> list[str]:
        """The calls that wrote to, or linked, the item `item_id`."""
        return [name for name, target in self.calls if target == item_id]


def resolve(tracker: RecordingTracker, reference: str, *, in_scope: bool = True) -> Item:
    titles = {item.title: item for item in tracker.known}
    return resolve_manual_parent(
        tracker,
        reference,
        expected="feature",
        in_scope=lambda item: in_scope,
        find_by_title=titles.get,
    )


def with_epic(title: str = TITLE) -> tuple[RecordingTracker, Item]:
    tracker = RecordingTracker()
    epic = tracker.add_epic(title)
    tracker.known.append(epic)
    return tracker, epic


def test_an_id_resolves_to_the_existing_item() -> None:
    tracker, epic = with_epic()

    assert resolve(tracker, epic.id).id == epic.id


def test_an_exact_title_resolves_to_the_existing_item() -> None:
    tracker, epic = with_epic()

    assert resolve(tracker, TITLE).id == epic.id


def test_a_part_of_a_title_does_not_resolve() -> None:
    tracker, _ = with_epic()

    with pytest.raises(ManualParentError):
        resolve(tracker, "Agent Assessment")


def test_an_item_of_another_type_is_refused_naming_the_id_and_both_types() -> None:
    tracker, _ = with_epic()
    other = tracker.create("story", "Not an epic")

    with pytest.raises(ManualParentError) as refused:
        resolve(tracker, other.id)

    message = str(refused.value)
    assert other.id in message and "story" in message and "feature" in message


def test_an_item_out_of_scope_is_refused() -> None:
    tracker, epic = with_epic()

    with pytest.raises(ManualParentError) as refused:
        resolve(tracker, epic.id, in_scope=False)

    assert epic.id in str(refused.value)


def test_the_change_item_is_created_under_the_manual_parent() -> None:
    tracker, epic = with_epic()

    item = create_change_item(tracker, "feature", "Change", "body", resolve(tracker, epic.id))

    assert item.parent_id == epic.id
    assert [child.id for child in tracker.children(epic.id)] == [item.id]


def test_over_the_whole_run_the_only_calls_on_the_manual_item_are_reads() -> None:
    tracker, epic = with_epic()

    parent = resolve(tracker, epic.id)
    create_change_item(tracker, "feature", "Change", "body", parent)
    tracker.children(epic.id)

    assert tracker.written(epic.id) == []
    assert tracker.get(epic.id) == epic


def test_a_change_with_no_line_has_a_change_item_with_no_parent() -> None:
    tracker, _ = with_epic()

    item = create_change_item(tracker, "feature", "Change", "body", None)

    assert item.parent_id is None
