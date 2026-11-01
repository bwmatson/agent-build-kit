"""A board for the start decision tests: the reconciler's world, with the board already pushed."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from agent_build_kit.pipeline.units import Unit
from agent_build_kit.trackers.local import LocalTracker
from tests.trackers.board_support import CHANGE, board_section, covering
from tests.trackers.reconciler_support import RecordingTracker, World

PERSON = "Alice Example"


def board(
    tmp_path: Path,
    levels: Sequence[str],
    covers: tuple[int, ...] = (1,),
    *,
    tracker: LocalTracker | None = None,
) -> tuple[World, Unit]:
    """A world whose items are on the board, and a planned unit covering `covers`."""
    unit = covering(f"{CHANGE}/1", covers)
    world = World(tmp_path, board_section(levels), tracker or RecordingTracker())
    world.run([unit])
    return world, unit


def item(world: World, key: str) -> str:
    """The id of the item the change's `key` (`1`, `1.2`) is on the board."""
    return world.item_id(f"{CHANGE}:{key}")


def taken_by_person(world: World, key: str) -> str:
    """Assign the item to a person, as the board does when they pick it up; its id."""
    item_id = item(world, key)
    assert isinstance(world.tracker, LocalTracker)
    world.tracker.as_identity(PERSON).claim(item_id)
    return item_id
