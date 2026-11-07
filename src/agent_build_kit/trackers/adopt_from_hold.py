"""Seeds the tracker mapping from the item ids a hold records (spec: external-hold-adoption).

Items a person made by hand are adopted, level by level, instead of being created again: each id
is read and checked, an adopted item keeps its wording and gains the marker line, and anything
that does not check out is a conflict for a person, with nothing created in its place.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path

from agent_build_kit.forges.transport import NotFound
from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.external_file import RELEASED, Hold, read_holds
from agent_build_kit.pipeline.task_progress import first_line_hash
from agent_build_kit.pipeline.tracker_file import (
    Synced,
    TaskEntry,
    TrackerFile,
    parent_item,
    read_tracker,
    write_tracker,
)
from agent_build_kit.trackers.base import STATUS_TAGS, Item, Tracker
from agent_build_kit.trackers.config import TrackerSection
from agent_build_kit.trackers.folders import tracker_read_dir, tracker_write_dir
from agent_build_kit.trackers.levels import task_group_key
from agent_build_kit.trackers.manual_parent import ManualParent
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


def _mapped_elsewhere(changes_dir: Path, state_dir: Path, name: str) -> dict[str, str]:
    """Each item id the other changes' tracker files record, with the change that has it."""
    mapped: dict[str, str] = {}
    folders = sorted(changes_dir.iterdir()) if changes_dir.is_dir() else []
    for folder in folders:
        if not folder.is_dir() or folder.name == name:
            continue
        try:
            found = read_tracker(tracker_read_dir(changes_dir, state_dir, folder.name))
        except Exception:  # an unusable file is reported for its own change
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
    ) -> None:
        self.tracker = tracker
        self.section = section
        self.name = name
        self.file = file
        self.elsewhere = elsewhere
        self.conflicts: list[str] = []
        self.blocked: set[str] = set()

    def conflict(self, marker: str, text: str) -> None:
        self.conflicts.append(f"{marker}: {text}")
        self.blocked.add(marker)

    def _read(self, marker: str, item_id: str) -> Item | None:
        try:
            return self.tracker.get(item_id)
        except (KeyError, NotFound):
            self.conflict(marker, f"item {item_id} does not exist on the tracker")
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
        """Record `found` for `wanted` as it stands, adding the marker line to its body."""
        if not self._checked(wanted, found):
            return
        line = f"<!-- {self.section.marker_prefix}:{wanted.marker} -->"
        if line not in found.body:
            body = f"{found.body}\n{line}" if found.body else line
            found = self.tracker.update(found.id, {"body": body}, found.revision)
        synced = Synced(
            id=found.id,
            fields={
                "title": found.title,
                "body": found.body,
                "state": found.kit_state or found.state,
                "tags": "; ".join(sorted(tag for tag in found.tags if tag in STATUS_TAGS)),
            },
            revision=found.revision,
            adopted=True,
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
            if (found := self._read(wanted.marker, item_id)) is not None:
                self._adopt(wanted, found)
        elif (found := self.tracker.find_by_marker(wanted.marker)) is not None:
            self._adopt(wanted, found)

    def epic(self, epic_id: str) -> None:
        """Record the manual parent, read and never written."""
        if self.file.epic is not None or not self.section.epic:
            return
        # Reading a manual parent is not part of the tracker protocol; the adapters that have an
        # epic level offer it (`ManualParentSource`).
        read: Callable[[str], ManualParent | None] = getattr(
            self.tracker, "read_manual_parent", lambda _: None
        )
        found = read(epic_id)
        if found is None:
            self.conflicts.append(f"epic: item {epic_id} does not exist on the tracker")
            return
        expected = self.section.level_types["epic"]
        if found.type.casefold() != expected.casefold():
            self.conflicts.append(f"epic: item {epic_id} is a {found.type!r}, not a {expected!r}")
            return
        self.file = self.file.model_copy(update={"epic": found.id})


def _seed_hold(seed: _Seed, hold: Hold, by_level: dict[str, list[WantedItem]]) -> None:
    groups = [
        item
        for item in by_level.get("group", [])
        if hold.scope == "all" or int(item.marker.rsplit(":", 1)[1]) in hold.scope
    ]
    group_ids = _ids(hold, _GROUP_KEYS)
    for index, item in enumerate(groups):
        if index < len(group_ids):
            seed.seed(item, group_ids[index])
        elif len(group_ids) == 1:
            # One item that covers several groups goes to the lowest.
            seed.conflict(
                item.marker,
                f"group item {group_ids[0]} covers it too and is adopted for "
                f"{groups[0].marker}: relink it by hand",
            )
        else:
            seed.seed(item, None)
    held = {item.marker for item in groups if item.marker in seed.file.groups}
    task_ids = _ids(hold, ("tasks",))
    tasks = [item for item in by_level.get("task", []) if task_group_key(item.marker) in held]
    for index, item in enumerate(tasks):
        seed.seed(item, task_ids[index] if index < len(task_ids) else None)


def seed_from_holds(
    tracker: Tracker,
    section: TrackerSection,
    files: dict[str, TrackerFile],
    wanted: Sequence[WantedItem],
    *,
    changes_dir: Path,
    state_dir: Path,
) -> Seeded:
    """Adopt the items the holds of each change in `files` record, by id and else by marker, and
    write each changed tracker file. `files` is updated in place."""
    conflicts: list[str] = []
    blocked: set[str] = set()
    for name, current in list(files.items()):
        holds = [hold for hold in read_holds(changes_dir / name) if hold.status != RELEASED]
        if not holds:
            continue
        elsewhere = _mapped_elsewhere(changes_dir, state_dir, name)
        seed = _Seed(tracker, section, name, current, elsewhere)
        mine = [item for item in wanted if item.marker.split(":", 1)[0] == name]
        by_level = {level: [i for i in mine if i.level == level] for level in section.levels}
        for hold in holds:
            for epic_id in _ids(hold, ("epic",)):
                seed.epic(epic_id)
        change_ids = [found for hold in holds for found in _ids(hold, _CHANGE_KEYS)]
        for item in by_level.get("change", []):
            seed.seed(item, change_ids[0] if change_ids else None)
        for hold in holds:
            _seed_hold(seed, hold, by_level)
        # A change whose items all conflict still gets its (empty) mapping, so it is on record
        # that the board was looked at.
        if seed.file != current or seed.conflicts:
            files[name] = seed.file
            write_tracker(tracker_write_dir(changes_dir, state_dir, name), seed.file)
        conflicts.extend(seed.conflicts)
        blocked |= seed.blocked
    return Seeded(conflicts=tuple(conflicts), blocked=frozenset(blocked))
