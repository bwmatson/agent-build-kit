"""The manual parent of a change: an item a person made, read and never written."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from agent_build_kit.trackers.base import Item, ItemKind, Tracker


class ManualParentError(ValueError):
    """The `Epic:` line names an item that cannot be the parent; the message says why."""


def resolve_manual_parent(
    tracker: Tracker,
    reference: str,
    *,
    expected: ItemKind,
    in_scope: Callable[[Item], bool],
    find_by_title: Callable[[str], Item | None],
) -> Item:
    """The existing item `reference` (an id or an exact title) names, by reads only.

    Raises ManualParentError naming the id, the kind found and the kind expected for an item of
    another kind, and for an item or title that is missing or out of scope."""
    if reference.isdigit():
        try:
            item = tracker.get(reference)
        except KeyError:
            raise ManualParentError(f"no board item has the id {reference}") from None
    else:
        found = find_by_title(reference)
        if found is None:
            raise ManualParentError("no board item has the title the `Epic:` line names")
        item = found
    if item.kind != expected:
        raise ManualParentError(
            f"item {item.id} is a {item.kind}, and the manual parent must be a {expected}"
        )
    if not in_scope(item):
        raise ManualParentError(f"item {item.id} is outside the board this repo syncs")
    return item


def create_change_item(
    tracker: Tracker,
    kind: ItemKind,
    title: str,
    body: str,
    parent: Item | None,
    *,
    markers: Sequence[str] = (),
) -> Item:
    """The change's top item, created under `parent` when there is one and at the top when not."""
    return tracker.create(kind, title, body, parent.id if parent else None, markers=markers)
