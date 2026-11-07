"""Seeds the tracker mapping from the item ids a hold records (spec: external-hold-adoption).

Items a person made by hand are adopted, level by level, instead of being created again: each id
is read and checked, an adopted item keeps its wording and gains the marker, and anything that
does not check out is a conflict for a person, with nothing created in its place.
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from pathlib import Path

from agent_build_kit.forges.transport import NotFound
from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.external_file import RELEASED, Hold, hold_groups, read_holds
from agent_build_kit.pipeline.task_progress import first_line_hash
from agent_build_kit.pipeline.tracker_file import (
    Synced,
    TaskEntry,
    TrackerFile,
    mapping_target,
    parent_item,
    read_for_target,
    with_manual_parent,
    write_tracker,
)
from agent_build_kit.trackers.base import Item, Tracker, UnknownWorkItemType, board_snapshot
from agent_build_kit.trackers.config import TrackerSection
from agent_build_kit.trackers.folders import tracker_read_dir, tracker_write_dir
from agent_build_kit.trackers.levels import task_group_key
from agent_build_kit.trackers.manual_parent import ManualParentError, ManualParentSource
from agent_build_kit.trackers.wanted_board import WantedItem

# The keys of a hold's `items` for a level, the older name second.
_CHANGE_KEYS = ("change", "feature")
_GROUP_KEYS = ("group", "story")


class Seeded(Frozen):
    """What seeding did: the conflicts to report and the markers the pass must neither adopt
    nor create."""

    conflicts: tuple[str, ...] = ()
    blocked: frozenset[str] = frozenset()


def _ids(hold: Hold, keys: Sequence[str]) -> list[str]:
    for key in keys:
        if (found := hold.items.get(key)) is not None:
            return [found] if isinstance(found, str) else list(found)
    return []


def _holds(changes_dir: Path, name: str) -> list[Hold]:
    return [hold for hold in read_holds(changes_dir / name) if hold.status != RELEASED]


def holding_changes(files: Collection[str], changes_dir: Path) -> list[str]:
    """The changes among `files` that have a hold not released."""
    return [name for name in files if _holds(changes_dir, name)]


def _mapped_elsewhere(
    section: TrackerSection, changes_dir: Path, state_dir: Path, name: str
) -> dict[str, str]:
    """Each item id the other changes' tracker files record for this board, with the change that
    has it."""
    mapped: dict[str, str] = {}
    folders = sorted(changes_dir.iterdir()) if changes_dir.is_dir() else []
    for folder in folders:
        if not folder.is_dir() or folder.name == name:
            continue
        where = tracker_read_dir(changes_dir, state_dir, folder.name)
        try:
            found = read_for_target(where, section.kind, mapping_target(section))
        except Exception:  # an unusable file, or another board's, is not a claim on an id
            continue
        if found is None:
            continue
        entries = [*found.groups.values(), *found.tasks.values()]
        if found.change:
            entries.append(found.change)
        mapped.update({entry.id: folder.name for entry in entries})
    return mapped


class _Seed:
    def __init__(
        self,
        tracker: Tracker,
        section: TrackerSection,
        name: str,
        file: TrackerFile,
        elsewhere: dict[str, str],
        written: dict[str, list[str]],
    ) -> None:
        self.tracker = tracker
        self.section = section
        self.name = name
        self.file = file
        self.elsewhere = elsewhere
        self.written = written
        self.conflicts: list[str] = []
        self.blocked: set[str] = set()

    def conflict(self, marker: str, text: str) -> None:
        self.conflicts.append(f"{marker}: {text}")
        self.blocked.add(marker)

    def _wrong_type(self, wanted: WantedItem, item_id: str, error: UnknownWorkItemType) -> None:
        self.conflict(wanted.marker, f"item {item_id} is not a {wanted.level} item: {error}")

    def _read(self, wanted: WantedItem, item_id: str) -> Item | None:
        try:
            return self.tracker.get(item_id)
        except (KeyError, NotFound):
            self.conflict(wanted.marker, f"item {item_id} does not exist on the tracker")
        except UnknownWorkItemType as error:
            self._wrong_type(wanted, item_id, error)
        return None

    def _checked(self, wanted: WantedItem, found: Item) -> bool:
        marker = wanted.marker
        if found.kind != wanted.level:
            self.conflict(
                marker, f"item {found.id} is a {found.kind} item, not a {wanted.level} item"
            )
            return False
        if (other := self.elsewhere.get(found.id)) is not None:
            self.conflict(
                marker, f"item {found.id} is already mapped to change {other}, not {self.name}"
            )
            return False
        expected = parent_item(self.file, self.section, wanted.level, marker)
        if wanted.level != "change" and expected is not None and found.parent_id != expected:
            self.conflict(
                marker,
                f"item {found.id} hangs under {found.parent_id}, not under the adopted item "
                f"{expected}",
            )
            return False
        return True

    def _adopt(self, wanted: WantedItem, found: Item) -> None:
        """Record `found` for `wanted` as it stands, making its marker find it."""
        if not self._checked(wanted, found):
            return
        if wanted.marker not in found.markers:
            found = self.tracker.add_marker(found.id, wanted.marker, found.revision)
            self.written.setdefault(found.id, []).append(found.revision)
        synced = Synced(
            id=found.id, fields=board_snapshot(found), revision=found.revision, adopted=True
        )
        self.elsewhere[found.id] = self.name
        if wanted.level == "change":
            self.file = self.file.model_copy(update={"change": synced})
        elif wanted.level == "group":
            groups = {**self.file.groups, wanted.marker: synced}
            self.file = self.file.model_copy(update={"groups": groups})
        else:
            entry = TaskEntry(**synced.model_dump(), text_hash=first_line_hash(wanted.body))
            tasks = {**self.file.tasks, wanted.marker: entry}
            self.file = self.file.model_copy(update={"tasks": tasks})

    def _recorded(self, wanted: WantedItem) -> bool:
        if wanted.level == "change":
            return self.file.change is not None
        if wanted.level == "group":
            return wanted.marker in self.file.groups
        return wanted.marker in self.file.tasks

    def seed(self, wanted: WantedItem, item_id: str | None) -> None:
        """Adopt the item `item_id` names for `wanted`, else the one its marker finds."""
        if self._recorded(wanted):
            return
        if item_id is not None:
            found = self._read(wanted, item_id)
        else:
            try:
                found = self.tracker.find_by_marker(wanted.marker)
            except UnknownWorkItemType as error:
                self._wrong_type(wanted, wanted.marker, error)
                return
        if found is not None:
            self._adopt(wanted, found)

    def epic(self, epic_id: str) -> None:
        """Record the manual parent, read and never written."""
        if self.file.epic is not None or not self.section.epic:
            return
        if not (
            hasattr(self.tracker, "read_manual_parent")
            and hasattr(self.tracker, "find_manual_parents")
        ):
            self.conflicts.append(f"epic: this tracker cannot read the manual parent {epic_id}")
            return
        source: ManualParentSource = self.tracker  # type: ignore[assignment]
        try:
            # The board's scope is not readable from an item, so every parent is in scope.
            self.file = with_manual_parent(
                self.file, self.section, epic_id, source, lambda _parent: True
            )
        except ManualParentError as error:
            self.conflicts.append(f"epic: {error}")


def _by_level(
    section: TrackerSection, wanted: Sequence[WantedItem], name: str
) -> dict[str, list[WantedItem]]:
    mine = [item for item in wanted if item.marker.split(":", 1)[0] == name]
    return {level: [i for i in mine if i.level == level] for level in section.levels}


def _hold_items(
    changes_dir: Path, name: str, hold: Hold, by_level: dict[str, list[WantedItem]]
) -> tuple[list[tuple[WantedItem, str | None]], list[WantedItem]]:
    """The group items of `hold` with the id each is to adopt (none: by marker), and the groups
    a single id covers beyond the lowest."""
    covered = hold_groups(changes_dir / name, hold)
    groups = [
        item for item in by_level.get("group", []) if int(item.marker.rsplit(":", 1)[1]) in covered
    ]
    ids = _ids(hold, _GROUP_KEYS)
    # One id that covers several groups goes to the lowest.
    extras = groups[1:] if len(ids) == 1 else []
    assigned = [
        (item, ids[index] if index < len(ids) else None)
        for index, item in enumerate(groups)
        if item not in extras
    ]
    return assigned, extras


def _task_pairs(
    hold: Hold, by_level: dict[str, list[WantedItem]], groups: Collection[str]
) -> list[tuple[WantedItem, str | None]]:
    ids = _ids(hold, ("tasks",))
    tasks = [item for item in by_level.get("task", []) if task_group_key(item.marker) in groups]
    return [(item, ids[index] if index < len(ids) else None) for index, item in enumerate(tasks)]


def _seed_hold(
    seed: _Seed, changes_dir: Path, hold: Hold, by_level: dict[str, list[WantedItem]]
) -> None:
    assigned, extras = _hold_items(changes_dir, seed.name, hold, by_level)
    for item in extras:
        lowest = assigned[0][0].marker
        seed.conflict(
            item.marker,
            f"the group item covering {lowest} covers it too: relink it by hand",
        )
    for item, item_id in assigned:
        seed.seed(item, item_id)
    held = {item.marker for item, _ in assigned if item.marker in seed.file.groups}
    for item, item_id in _task_pairs(hold, by_level, held):
        seed.seed(item, item_id)


def claimed_markers(
    section: TrackerSection,
    files: Collection[str],
    wanted: Sequence[WantedItem],
    changes_dir: Path,
) -> frozenset[str]:
    """The markers a hold records an id for, which a real pass adopts or reports and never
    creates. Reads no tracker and writes nothing."""
    claimed: set[str] = set()
    for name in files:
        by_level = _by_level(section, wanted, name)
        for hold in _holds(changes_dir, name):
            if _ids(hold, _CHANGE_KEYS):
                claimed.update(item.marker for item in by_level.get("change", []))
            assigned, extras = _hold_items(changes_dir, name, hold, by_level)
            claimed.update(item.marker for item in extras)
            claimed.update(item.marker for item, item_id in assigned if item_id is not None)
            held = {item.marker for item, item_id in assigned if item_id is not None}
            claimed.update(
                item.marker for item, item_id in _task_pairs(hold, by_level, held) if item_id
            )
    return frozenset(claimed)


def seed_from_holds(
    tracker: Tracker,
    section: TrackerSection,
    files: dict[str, TrackerFile],
    wanted: Sequence[WantedItem],
    *,
    changes_dir: Path,
    state_dir: Path,
    written: dict[str, list[str]],
) -> Seeded:
    """Adopt the items the holds of each change in `files` record, by id and else by marker, and
    write each changed tracker file. `files` is updated in place, and the revision of each write
    the kit made to the board is added to `written` as it is made."""
    conflicts: list[str] = []
    blocked: set[str] = set()
    for name in holding_changes(list(files), changes_dir):
        current = files[name]
        elsewhere = _mapped_elsewhere(section, changes_dir, state_dir, name)
        seed = _Seed(tracker, section, name, current, elsewhere, written)
        by_level = _by_level(section, wanted, name)
        holds = _holds(changes_dir, name)
        for hold in holds:
            for epic_id in _ids(hold, ("epic",)):
                seed.epic(epic_id)
        change_ids = [found for hold in holds for found in _ids(hold, _CHANGE_KEYS)]
        for item in by_level.get("change", []):
            seed.seed(item, change_ids[0] if change_ids else None)
        for hold in holds:
            _seed_hold(seed, changes_dir, hold, by_level)
        # A change whose items all conflict still gets its (empty) mapping, so it is on record
        # that the board was looked at.
        if seed.file != current or seed.conflicts:
            files[name] = seed.file
            write_tracker(tracker_write_dir(changes_dir, state_dir, name), seed.file)
        conflicts.extend(seed.conflicts)
        blocked |= seed.blocked
    return Seeded(conflicts=tuple(conflicts), blocked=frozenset(blocked))
