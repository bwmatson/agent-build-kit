"""Pushes the wanted board to a repo's tracker, making only the calls that differ.

Spec: tracker-push. Level by level from the outermost, each item is looked up by its marker
before it is created, updated only where the wanted fields differ from the snapshot recorded in
the change's `tracker.yaml` and the tracker's revision still equals the snapshot's, and every
success is recorded before the next call. A tracker failure is contained: it is logged and
counted, and never raised.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Collection, Mapping, Sequence
from pathlib import Path

from agent_build_kit import telemetry, trackers
from agent_build_kit.forges.transport import AuthError, RateLimited
from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.file_lock import atomic_write_text
from agent_build_kit.pipeline.task_progress import first_line_hash
from agent_build_kit.pipeline.tracker_file import (
    Synced,
    TargetMismatch,
    TaskEntry,
    TrackerFile,
    mapping_target,
    read_for_target,
    write_tracker,
)
from agent_build_kit.pipeline.units import Unit
from agent_build_kit.trackers.base import StaleRevision, Tracker
from agent_build_kit.trackers.config import TrackerConfigError, section_for
from agent_build_kit.trackers.wanted_board import WantedItem, wanted_board

ERRORS_COUNTER = "abk.tracker.errors"


class PassReport(Frozen):
    """What one pass did. `awaiting` holds the markers of items left for the inbound sync because
    the board changed them; `stopped` is set when a rate limit ended the pass."""

    created: int = 0
    updated: int = 0
    errors: int = 0
    awaiting: tuple[str, ...] = ()
    stopped: bool = False


def _fields(item: WantedItem) -> dict[str, str]:
    return {
        "title": item.title,
        "body": item.body,
        "state": item.state,
        "tags": "; ".join(item.tags),
    }


def _recorded(tracker_file: TrackerFile, item: WantedItem) -> Synced | None:
    if item.level == "change":
        return tracker_file.change
    if item.level == "group":
        return tracker_file.groups.get(item.marker)
    return tracker_file.tasks.get(item.marker)


def _with(tracker_file: TrackerFile, item: WantedItem, synced: Synced) -> TrackerFile:
    if item.level == "change":
        return tracker_file.model_copy(update={"change": synced})
    if item.level == "group":
        return tracker_file.model_copy(
            update={"groups": {**tracker_file.groups, item.marker: synced}}
        )
    entry = TaskEntry(**synced.model_dump(), text_hash=first_line_hash(item.body))
    return tracker_file.model_copy(update={"tasks": {**tracker_file.tasks, item.marker: entry}})


def _entries(tracker_file: TrackerFile, change: str) -> dict[str, Synced]:
    """Every recorded item of a change by marker."""
    found: dict[str, Synced] = {**tracker_file.groups, **tracker_file.tasks}
    if tracker_file.change:
        found[change] = tracker_file.change
    return found


class _Pass:
    def __init__(
        self,
        repo: str,
        tracker: Tracker,
        files: dict[str, TrackerFile],
        changes_dir: Path,
        log: Callable[[str], None],
    ) -> None:
        self.repo = repo
        self.tracker = tracker
        self.files = files
        self.changes_dir = changes_dir
        self.log = log
        self.created = 0
        self.updated = 0
        self.errors = 0
        self.awaiting: list[str] = []

    def push(self, item: WantedItem) -> None:
        name = item.marker.split(":", 1)[0]
        tracker_file = self.files[name]
        parent = item.parent_id
        if parent is None and item.parent_marker is not None:
            parent = self._id_of(name, item.parent_marker)
            if parent is None:  # the parent has no item yet: its subtree waits for the next tick
                return
        wanted = _fields(item)
        synced = _recorded(tracker_file, item)
        if synced is None:
            synced = self._create_or_adopt(name, item, parent, wanted)
            tracker_file = self.files[name]
        changes = {key: value for key, value in wanted.items() if synced.fields.get(key) != value}
        if not changes:
            return
        current = self.tracker.get(synced.id)
        if current.revision != synced.revision:
            self.awaiting.append(item.marker)
            return
        try:
            updated = self.tracker.update(synced.id, changes, synced.revision)
        except StaleRevision:
            self.awaiting.append(item.marker)
            return
        self.updated += 1
        self._record(name, item, Synced(id=updated.id, fields=wanted, revision=updated.revision))

    def _id_of(self, change: str, marker: str) -> str | None:
        found = _entries(self.files[change], change).get(marker)
        return found.id if found else None

    def _create_or_adopt(
        self, change: str, item: WantedItem, parent: str | None, wanted: Mapping[str, str]
    ) -> Synced:
        found = self.tracker.find_by_marker(item.marker)
        if found is not None:
            snapshot = {
                "title": found.title,
                "body": found.body,
                "state": found.state,
                "tags": wanted["tags"],
            }
            synced = Synced(id=found.id, fields=snapshot, revision=found.revision)
        else:
            made = self.tracker.create(
                item.level, item.title, item.body, parent, markers=(item.marker,)
            )
            self.created += 1
            snapshot = {"title": item.title, "body": item.body, "state": made.state, "tags": ""}
            synced = Synced(id=made.id, fields=snapshot, revision=made.revision)
        self._record(change, item, synced)
        return synced

    def _record(self, change: str, item: WantedItem, synced: Synced) -> None:
        self.files[change] = _with(self.files[change], item, synced)
        write_tracker(self.changes_dir / change, self.files[change])


def _write_snapshot(path: Path, files: Mapping[str, TrackerFile]) -> None:
    """The machine-local cache of ids and revisions; losing it costs reads, not duplicates."""
    items = {
        marker: {"id": entry.id, "revision": entry.revision}
        for change, tracker_file in files.items()
        for marker, entry in _entries(tracker_file, change).items()
    }
    atomic_write_text(path, json.dumps(items, indent=2, sort_keys=True))


def reconcile(
    repo: str,
    *,
    changes_dir: Path,
    changes: Sequence[str],
    units: Sequence[Unit],
    repo_url: str,
    state_dir: Path,
    tracking_dir: Path | None = None,
    archived: Collection[str] = (),
    log: Callable[[str], None] = print,
) -> PassReport:
    """One pass over `repo`'s tracker: level by level, create what has no item (looking for its
    marker first), update what differs from the recorded snapshot, and record each success before
    the next call. `state_dir` holds the machine-local snapshot. Never raises for a tracker
    failure."""
    try:
        section = section_for(repo)
        tracker = trackers.for_repo(repo)
    except TrackerConfigError as error:
        log(f"tracker {repo}: skipped: {error}")
        return PassReport()
    if section is None or tracker is None:
        return PassReport()

    target = mapping_target(section)
    files: dict[str, TrackerFile] = {}
    kept: list[str] = []
    errors = 0
    for name in changes:
        try:
            found = read_for_target(changes_dir / name, section.kind, target)
        except TargetMismatch as error:
            log(f"tracker {repo}: {error}")
            errors += 1
            continue
        files[name] = found or TrackerFile(kind=section.kind, target=target)
        kept.append(name)
    epics = {name: tracker_file.epic for name, tracker_file in files.items() if tracker_file.epic}
    wanted = wanted_board(
        section,
        changes_dir,
        kept,
        units,
        repo_url=repo_url,
        epics=epics,
        archived=archived,
        tracking_dir=tracking_dir,
    )

    run = _Pass(repo, tracker, files, changes_dir, log)
    run.errors = errors
    stopped = False
    failed = False
    for item in wanted:
        if item.state == "removed":
            continue
        try:
            run.push(item)
        except RateLimited as error:
            log(f"tracker {repo}: rate limited, resuming next tick: {error}")
            stopped = True
            break
        except AuthError as error:
            log(f"tracker {repo}: credential refused, no item pushed this tick: {error}")
            failed = True
            break
        except (
            Exception
        ) as error:  # the host answers in its own errors; one item never stops the rest
            run.errors += 1
            telemetry.count(ERRORS_COUNTER, repo=repo)
            log(f"tracker {repo}: {item.marker}: {error}")
    if not failed:
        _write_snapshot(state_dir / f"tracker-{repo}.json", run.files)
    return PassReport(
        created=run.created,
        updated=run.updated,
        errors=run.errors,
        awaiting=tuple(run.awaiting),
        stopped=stopped,
    )
