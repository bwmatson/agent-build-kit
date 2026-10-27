"""The tracker file of a change: which tracker item belongs to the change and to each of its tasks
(spec: tracker-mapping).

`tracker.yaml` in a change's folder records the tracker kind and a target label, the Feature's
item and a map from task key to item. It is not part of the plan hash and is written only by the
pipeline, whole and under the change's tasks lock, the one the checkbox writes take.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import yaml

from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.file_lock import atomic_write_text
from agent_build_kit.pipeline.task_progress import first_line_hash, tasks_lock
from agent_build_kit.pipeline.units import Unit
from agent_build_kit.pipeline.work_graph import Task

FILE_NAME = "tracker.yaml"
SCHEMA_VERSION = 1


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
    feature: Synced | None = None
    tasks: dict[str, TaskEntry] = {}


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


class StoryMapping(Frozen):
    """Where a unit's Story sits: the Feature of the unit's own change as its parent, and the
    Features of the other changes whose groups the unit carries as related."""

    parent: str
    related: tuple[str, ...] = ()


def story_mapping(unit: Unit, features: Mapping[str, str]) -> StoryMapping:
    """The mapping for a unit's Story, from each change's Feature id."""
    return StoryMapping(
        parent=features[unit.change],
        related=tuple(
            features[member.change]
            for member in unit.members()
            if member.change != unit.change and member.change in features
        ),
    )
