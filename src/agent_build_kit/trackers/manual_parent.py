"""The manual parent of a change: an item a person made, read and never written.

It is not one of the kit's levels, so it is read as a `ManualParent` (its board type as a
string) and not as an `Item`, whose kind is a level.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Protocol

from agent_build_kit.model import Frozen


class ManualParent(Frozen):
    """An existing board item that may stand above a change: its id, title and board type."""

    id: str
    title: str
    type: str


class ManualParentError(ValueError):
    """The `Epic:` line names an item that cannot be the parent; the message says why."""


class ManualParentSource(Protocol):
    """The two reads a tracker offers to find a manual parent; neither writes."""

    def read_manual_parent(self, item_id: str) -> ManualParent | None:
        """The item with this id, whatever its type; none when the board has no such item,
        including when the text is not the shape of an id."""
        ...

    def find_manual_parents(self, title: str) -> Sequence[ManualParent]:
        """The candidates a title search turns up. It may match loosely (a substring, any
        case): the caller keeps the exact ones."""
        ...


def resolve_manual_parent(
    source: ManualParentSource,
    reference: str,
    *,
    expected: str,
    in_scope: Callable[[ManualParent], bool],
) -> ManualParent:
    """The existing item `reference` (an id, else an exact title) names, by reads only.

    Raises ManualParentError for an item or title that is missing or that two items share, for
    an item of another board type than `expected` (naming the id and both types) and for an item
    out of scope."""
    found = source.read_manual_parent(reference)
    if found is None:
        exact = [c for c in source.find_manual_parents(reference) if c.title == reference]
        if not exact:
            raise ManualParentError(f"no board item has the id or the exact title {reference!r}")
        if len(exact) > 1:
            ids = ", ".join(c.id for c in exact)
            raise ManualParentError(f"the title {reference!r} is shared by items {ids}; use an id")
        found = exact[0]
    if found.type != expected:
        raise ManualParentError(
            f"item {found.id} is a {found.type!r}, and the manual parent must be a {expected!r}"
        )
    if not in_scope(found):
        raise ManualParentError(f"item {found.id} is outside the board this repo syncs")
    return found
