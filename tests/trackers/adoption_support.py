"""A board with hand-made items and the hold that records them, for the tests of what the sync
does once the items are adopted (spec: external-hold-adoption)."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

from agent_build_kit.pipeline.external_file import Hold, write_holds
from agent_build_kit.trackers.base import Item
from agent_build_kit.trackers.local import EPIC_TYPE
from tests.trackers.board_support import board_section
from tests.trackers.reconciler_support import RecordingTracker, World


def hold_with(
    world: World, items: Mapping[str, str | list[str]], scope: tuple[int, ...] = (1,)
) -> None:
    """Record a hold on `scope` carrying the item ids `items`."""
    write_holds(
        world.change_dir,
        [
            Hold(
                scope=scope,
                holder="Sam Example",
                link="https://boards.example/items/42",
                since=datetime(2026, 1, 1, tzinfo=UTC),
                items=dict(items),
            )
        ],
    )


def adopted_board(tmp_path: Path, levels: list[str]) -> tuple[World, Item, Item]:
    """A world whose board holds a change item and a group item a person made by hand, and a
    hold on group 1 that records both; the two items."""
    world = World(tmp_path, board_section(levels, epic_type=EPIC_TYPE), RecordingTracker())
    change = world.tracker.create("change", "Remember lanes", "", None)
    group = world.tracker.create("group", "Sam's own wording", "", change.id)
    world.tracker.calls.clear()
    hold_with(world, {"change": change.id, "group": group.id})
    return world, change, group
