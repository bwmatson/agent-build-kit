"""A board for the start decision tests: the reconciler's world, with the board already pushed."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.units import Unit
from agent_build_kit.trackers.local import LocalTracker
from tests.split_start_support import installation
from tests.trackers.board_support import CHANGE, board_section, covering
from tests.trackers.reconciler_support import RecordingTracker, World

PERSON = "Alice Example"
FIRST = f"{CHANGE}/1"
SECOND = f"{CHANGE}/2"


def board_in(tmp_path: Path) -> tuple[World, Installation]:
    """The installation of a repo with a tracker, and its board pushed into the changes folder
    the round reads."""
    inst = installation(tmp_path, acp=True, project_limits={"max_units_in_progress": 5})
    folder = inst.changes_dir.parent
    folder.mkdir(parents=True, exist_ok=True)
    world = World(folder, board_section(["change", "group"]), RecordingTracker())
    world.run([covering(FIRST, (1,)), covering(SECOND, (2,))])
    return world, inst


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
