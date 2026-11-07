"""A board with a person acting on it, and the apply step run over what they changed."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from agent_build_kit.pipeline.unit_store import StoredUnit, UnitStore
from agent_build_kit.pipeline.units import Member, UnitState
from agent_build_kit.trackers.apply import Applied, apply_changes
from agent_build_kit.trackers.local import LocalTracker
from agent_build_kit.trackers.poll import poll_board
from tests.factories import stored_unit
from tests.trackers.board_support import CHANGE, board_section, write_change
from tests.trackers.reconciler_support import RecordingTracker, World

PERSON = "alice@example.test"
PERSON_NAME = "Alice Example"


class NamedBoard(RecordingTracker):
    """The recording stand-in on which a person's assignment carries a display name."""

    def assign_as_person(self, item_id: str) -> None:
        self.person().set_assignee(item_id, PERSON)
        named = self._items[item_id].model_copy(update={"assignee_names": (PERSON_NAME,)})
        self._items[item_id] = named

    def clear_as_person(self, item_id: str) -> None:
        self.person().set_assignee(item_id, "")
        self._items[item_id] = self._items[item_id].model_copy(update={"assignee_names": ()})

    def person(self) -> LocalTracker:
        """The board seen as the person, for edits, new items and state changes."""
        return self.as_identity(PERSON)


class AppliedBoard:
    """A mirrored change, a unit store and the two steps of an inbound tick: poll, then apply."""

    def __init__(
        self,
        tmp_path: Path,
        levels: list[str],
        units: Sequence[StoredUnit] = (),
        *,
        also: Sequence[str] = (),
    ) -> None:
        """`also` names further changes, each with the fixture's tasks, mirrored beside it."""
        self.world = World(tmp_path, board_section(levels), NamedBoard())
        self.store = UnitStore(tmp_path / "units.json")
        self.store.import_units(list(units))
        for name in also:
            write_change(self.world.changes_dir, name)
        self.world.run(changes=(CHANGE, *also))
        poll_board("app", state_dir=self.world.state_dir, log=self.world.logs.append)

    @property
    def board(self) -> NamedBoard:
        board = self.world.tracker
        assert isinstance(board, NamedBoard)
        return board

    @property
    def tasks(self) -> Path:
        return self.world.change_dir / "tasks.md"

    def item_id(self, key: str, change: str = CHANGE) -> str:
        """The board item of the group or task `key` (`1`, `2.1`) of `change`."""
        return self.world.item_id(f"{change}:{key}")

    def apply(self) -> Applied:
        changes = poll_board("app", state_dir=self.world.state_dir, log=self.world.logs.append)
        return apply_changes(
            "app",
            changes,
            changes_dir=self.world.changes_dir,
            store=self.store,
            log=self.world.logs.append,
        )

    def unit(self, uid: str) -> StoredUnit:
        return self.store.get(uid)


def building(
    uid: str,
    *groups: int,
    state: UnitState = UnitState.RUNNING,
    joined: Sequence[Member] = (),
) -> StoredUnit:
    """A unit of the fixture change that builds `groups`, with the members it joined."""
    return stored_unit(
        uid,
        change=CHANGE,
        groups=groups,
        state=state,
        branch=f"spec/{uid}",
        joined=tuple(joined),
    )
