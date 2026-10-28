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
    raise NotImplementedError


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
    raise NotImplementedError
