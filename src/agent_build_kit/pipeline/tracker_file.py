"""The tracker file of a change: which tracker item belongs to the change, to each of its groups
and to each of its tasks (spec: tracker-mapping, tracker-levels).

`tracker.yaml` in a change's folder records the tracker kind and a target label carrying a hash
of the level mapping (`mapping_target`), the change's item, the manual epic's id, a map from group
key to item and a map from task key to item. A version 1 file is still read, its Feature as the
change item. It is not part of the plan hash and is written only by the
pipeline, whole and under the change's tasks lock, the one the checkbox writes take.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml
from pydantic import model_validator

from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.file_lock import atomic_write_text
from agent_build_kit.pipeline.task_progress import first_line_hash, tasks_lock
from agent_build_kit.pipeline.work_graph import Task
from agent_build_kit.trackers.config import TrackerSection
from agent_build_kit.trackers.levels import task_group_key
from agent_build_kit.trackers.manual_parent import (
    ManualParent,
    ManualParentSource,
    resolve_manual_parent,
)

FILE_NAME = "tracker.yaml"
SCHEMA_VERSION = 2


class TargetMismatch(ValueError):
    """The file records another board than the configuration names; the message names the
    change and both targets."""


class Synced(Frozen):
    """A tracker item as last synced: its id, the fields then written and its revision."""

    id: str
    fields: dict[str, str] = {}
    revision: str = ""


class TaskEntry(Synced):
    """A task's item, with the hash of the first line of the task's text when it was recorded."""

    text_hash: str


class TrackerFile(Frozen):
    """What `tracker.yaml` holds. `target` is a short label, never a secret."""

    schema_version: int = SCHEMA_VERSION
    kind: str
    target: str
    # The change's item, the manual epic's id and the group items by `<change>:<group>`.
    change: Synced | None = None
    epic: str | None = None
    groups: dict[str, Synced] = {}
    tasks: dict[str, TaskEntry] = {}

    @model_validator(mode="before")
    @classmethod
    def _read_version_1(cls, raw: Any) -> Any:
        """A version 1 file's `feature` is the change item."""
        if isinstance(raw, dict) and raw.get("schema_version") == 1:
            old = dict(raw)
            if "feature" in old:
                old["change"] = old.pop("feature")
            old["schema_version"] = SCHEMA_VERSION
            return old
        return raw


def mapping_target(section: TrackerSection) -> str:
    """The section's target with a short hash of its level mapping (levels, types, epic setting)."""
    # An epic type is part of the mapping only when the epic level is on.
    types = {
        level: kind
        for level, kind in section.level_types.items()
        if level != "epic" or section.epic
    }
    mapping = {"levels": section.levels, "types": types, "epic": section.epic}
    digest = hashlib.sha256(json.dumps(mapping, sort_keys=True).encode()).hexdigest()
    return f"{section.target}@{digest[:8]}"


def tracker_path(change_dir: Path) -> Path:
    """Where `change_dir` keeps its tracker file."""
    return change_dir / FILE_NAME


def read_tracker(change_dir: Path) -> TrackerFile | None:
    """The change's tracker file, none when it has none. Creates nothing. The file is replaced
    whole, so a read needs no lock."""
    path = tracker_path(change_dir)
    if not path.is_file():
        return None
    return TrackerFile.model_validate(yaml.safe_load(path.read_text()) or {})


def write_tracker(change_dir: Path, tracker: TrackerFile) -> None:
    """Replace the file whole, under the change's tasks lock, the one the checkbox writes take."""
    text = yaml.safe_dump(tracker.model_dump(mode="json"), sort_keys=False)
    with tasks_lock(change_dir / "tasks.md"):
        atomic_write_text(tracker_path(change_dir), text)


def read_for_target(change_dir: Path, kind: str, target: str) -> TrackerFile | None:
    """`read_tracker`, but raises `TargetMismatch` when the file records another kind or target,
    so the old ids are not used."""
    found = read_tracker(change_dir)
    if found is not None and (found.kind, found.target) != (kind, target):
        raise TargetMismatch(
            f"change {change_dir.name} records {found.kind} {found.target}, "
            f"but the configuration names {kind} {target}"
        )
    return found


class Reconciled(Frozen):
    """A tracker file matched against the tasks now in the file: the mapping with pure moves
    applied, the moves made (old key to new), the keys left to create or remove, the entries a
    move displaced from the key it landed on (their items are for the caller to remove), and the
    conflicts a person must settle."""

    tracker: TrackerFile
    moved: dict[str, str] = {}
    created: tuple[str, ...] = ()
    removed: tuple[str, ...] = ()
    displaced: tuple[TaskEntry, ...] = ()
    conflicts: tuple[str, ...] = ()


def reconcile_moves(tracker: TrackerFile, tasks: list[Task]) -> Reconciled:
    """Match recorded keys that are gone, or whose line now reads differently, to keys whose line
    has the same first-line hash. A key edited in place with no match elsewhere stays as it is."""
    present = {task.key: first_line_hash(task.text) for task in tasks}
    absent = [key for key in tracker.tasks if key not in present]
    stale = [
        key
        for key, entry in tracker.tasks.items()
        if present.get(key, entry.text_hash) != entry.text_hash
    ]
    candidates = [key for key in present if key not in tracker.tasks] + stale
    moved: dict[str, str] = {}
    conflicts: list[str] = []
    for key in [*absent, *stale]:
        wanted = tracker.tasks[key].text_hash
        matches = [new for new in candidates if present[new] == wanted and new != key]
        if len(matches) == 1 and matches[0] not in moved.values():
            moved[key] = matches[0]
        elif matches:
            conflicts.append(f"{key} matches {', '.join(matches)}; a person must settle it")
    if conflicts:
        return Reconciled(tracker=tracker, conflicts=tuple(conflicts))
    kept = {key: entry for key, entry in tracker.tasks.items() if key not in moved}
    displaced = tuple(kept[new] for new in moved.values() if new in kept)
    for old, new in moved.items():
        kept[new] = tracker.tasks[old]
    return Reconciled(
        tracker=tracker.model_copy(update={"tasks": kept}),
        moved=moved,
        created=tuple(key for key in present if key not in kept),
        removed=tuple(key for key in absent if key not in moved),
        displaced=displaced,
    )


def with_manual_parent(
    tracker: TrackerFile,
    section: TrackerSection,
    reference: str | None,
    source: ManualParentSource,
    in_scope: Callable[[ManualParent], bool],
) -> TrackerFile:
    """The file with the manual parent the change's `Epic:` line (`reference`) names recorded as
    `epic`, resolved by reads only. It is the file unchanged when there is no line, when the
    section has no epic level, or when an epic is already recorded: it resolves once."""
    if reference is None or not section.epic or tracker.epic is not None:
        return tracker
    found = resolve_manual_parent(
        source, reference, expected=section.level_types["epic"], in_scope=in_scope
    )
    return tracker.model_copy(update={"epic": found.id})


def parent_item(tracker: TrackerFile, section: TrackerSection, level: str, key: str) -> str | None:
    """The id of the recorded item that the item `key` of `level` hangs under, by the section's
    levels: the group item for a level under the groups, the change item for a level under the
    change, the epic for the first level when one is set. None when there is no parent or it is
    not recorded."""
    parent = section.parent_level(level)
    if parent == "epic":
        return tracker.epic
    if parent == "change":
        return tracker.change.id if tracker.change else None
    if parent == "group":
        found = tracker.groups.get(task_group_key(key))
        return found.id if found else None
    return None
