"""The tracker file of a change: which tracker item belongs to the change and to each of its tasks
(spec: tracker-mapping).

`tracker.yaml` in a change's folder records the tracker kind and a target label, the Feature's
item and a map from task key to item. It is not part of the plan hash and is written only by the
pipeline, whole and under the change's tasks lock, the one the checkbox writes take.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.file_lock import atomic_write_text
from agent_build_kit.pipeline.task_progress import tasks_lock
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
    applied, the moves made (old key to new), the keys left to create or remove, and the
    conflicts a person must settle."""

    tracker: TrackerFile
    moved: dict[str, str] = {}
    created: tuple[str, ...] = ()
    removed: tuple[str, ...] = ()
    conflicts: tuple[str, ...] = ()


def reconcile_moves(tracker: TrackerFile, tasks: list[Task]) -> Reconciled:
    """Match recorded keys that are gone to unrecorded keys with the same first-line hash."""
    raise NotImplementedError
