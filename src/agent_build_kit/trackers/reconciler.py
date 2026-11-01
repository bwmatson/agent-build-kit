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
from agent_build_kit.forges.transport import (
    AuthError,
    HostError,
    HostUnavailable,
    NotFound,
    RateLimited,
)
from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.file_lock import atomic_write_text
from agent_build_kit.pipeline.task_progress import first_line_hash
from agent_build_kit.pipeline.tracker_file import (
    Synced,
    TaskEntry,
    TrackerFile,
    mapping_target,
    parent_item,
    read_for_target,
    write_tracker,
)
from agent_build_kit.pipeline.units import Unit
from agent_build_kit.trackers.base import STATUS_TAGS, StaleRevision, Tracker
from agent_build_kit.trackers.config import TrackerConfigError, TrackerSection, section_for
from agent_build_kit.trackers.wanted_board import WantedItem, wanted_board

ERRORS_COUNTER = "abk.tracker.errors"
SNAPSHOT_ITEMS = "items"

# What ends the whole pass: the tracker as a whole fails, so every item would fail the same way.
_REPO_FAILURES = (AuthError, HostError, HostUnavailable)


class PassReport(Frozen):
    """What one pass did. `awaiting` holds the markers of items left for the inbound sync because
    the board changed them; `stopped` is set when a rate limit ended the pass and `failed` when
    the tracker as a whole failed (credential, target or outage), which counts as one error."""

    created: int = 0
    updated: int = 0
    errors: int = 0
    awaiting: tuple[str, ...] = ()
    stopped: bool = False
    failed: bool = False


class _RepoFailed(Exception):
    """A project-scoped call found no project: the target is wrong for every item."""


def _fields(item: WantedItem) -> dict[str, str]:
    return {
        "title": item.title,
        "body": item.body,
        "state": item.state,
        "tags": "; ".join(sorted(item.tags)),
    }


def _entries(tracker_file: TrackerFile, change: str) -> dict[str, Synced]:
    """Every recorded item of a change by marker."""
    found: dict[str, Synced] = {**tracker_file.groups, **tracker_file.tasks}
    if tracker_file.change:
        found[change] = tracker_file.change
    return found


def _with(tracker_file: TrackerFile, item: WantedItem, synced: Synced) -> TrackerFile:
    if item.level == "change":
        return tracker_file.model_copy(update={"change": synced})
    if item.level == "group":
        return tracker_file.model_copy(
            update={"groups": {**tracker_file.groups, item.marker: synced}}
        )
    entry = TaskEntry(**synced.model_dump(), text_hash=first_line_hash(item.body))
    return tracker_file.model_copy(update={"tasks": {**tracker_file.tasks, item.marker: entry}})


class _Pass:
    def __init__(
        self,
        tracker: Tracker,
        section: TrackerSection,
        files: dict[str, TrackerFile],
        changes_dir: Path,
    ) -> None:
        self.tracker = tracker
        self.section = section
        self.files = files
        self.changes_dir = changes_dir
        self.created = 0
        self.updated = 0
        self.awaiting: list[str] = []

    def push(self, item: WantedItem) -> None:
        name = item.marker.split(":", 1)[0]
        parent = parent_item(self.files[name], self.section, item.level, item.marker)
        if parent is None and item.parent_marker is not None:
            return  # the parent has no item yet: its subtree waits for the next tick
        wanted = _fields(item)
        synced = _entries(self.files[name], name).get(item.marker)
        if synced is None:
            synced = self._create_or_adopt(name, item, parent, wanted)
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

    def _create_or_adopt(
        self, change: str, item: WantedItem, parent: str | None, wanted: Mapping[str, str]
    ) -> Synced:
        """The item on the board for `item`: the one its marker finds, else a new one. The snapshot
        holds what the board shows in the kit's words, so the next diff compares like with like."""
        try:
            found = self.tracker.find_by_marker(item.marker)
        except NotFound as error:
            raise _RepoFailed(str(error)) from error
        if found is not None:
            snapshot = {
                "title": found.title,
                "body": found.body,
                "state": found.kit_state or found.state,
                "tags": "; ".join(sorted(tag for tag in found.tags if tag in STATUS_TAGS)),
            }
            synced = Synced(id=found.id, fields=snapshot, revision=found.revision)
        else:
            made = self.tracker.create(
                item.level, item.title, item.body, parent, markers=(item.marker,)
            )
            self.created += 1
            snapshot = {
                "title": item.title,
                "body": item.body,
                "state": made.kit_state or made.state,
                "tags": "",
            }
            synced = Synced(id=made.id, fields=snapshot, revision=made.revision)
        self._record(change, item, synced)
        return synced

    def _record(self, change: str, item: WantedItem, synced: Synced) -> None:
        self.files[change] = _with(self.files[change], item, synced)
        write_tracker(self.changes_dir / change, self.files[change])


def _write_snapshot(path: Path, files: Mapping[str, TrackerFile]) -> None:
    """Record the ids and revisions the pass ended with, in the machine-local file. Nothing reads
    them to save calls yet; the pass trusts `tracker.yaml` and the marker search. Any other key
    in the file (the mirror's dirty mark) is kept."""
    try:
        kept = json.loads(path.read_text())
    except (OSError, ValueError):
        kept = {}
    kept = kept if isinstance(kept, dict) else {}
    kept[SNAPSHOT_ITEMS] = {
        marker: {"id": entry.id, "revision": entry.revision}
        for change, tracker_file in files.items()
        for marker, entry in _entries(tracker_file, change).items()
    }
    atomic_write_text(path, json.dumps(kept, indent=2, sort_keys=True))


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

    def count_error() -> None:
        telemetry.count(ERRORS_COUNTER, repo=repo)

    target = mapping_target(section)
    files: dict[str, TrackerFile] = {}
    errors = 0
    for name in changes:
        try:
            found = read_for_target(changes_dir / name, section.kind, target)
        except Exception as error:  # a mismatch, a conflicted file or a bad field: this change only
            errors += 1
            count_error()
            log(f"tracker {repo}: change {name}: its tracker file is unusable: {error}")
            continue
        files[name] = found or TrackerFile(kind=section.kind, target=target)
    epics = {name: tracker_file.epic for name, tracker_file in files.items() if tracker_file.epic}
    wanted = wanted_board(
        section,
        changes_dir,
        list(files),
        units,
        repo_url=repo_url,
        epics=epics,
        archived=archived,
        tracking_dir=tracking_dir,
    )

    run = _Pass(tracker, section, files, changes_dir)
    stopped = failed = False
    for item in wanted:
        # A group that is no longer wanted keeps what its item last showed: nothing is deleted.
        if item.state == "removed":
            continue
        try:
            run.push(item)
        except RateLimited as error:
            log(f"tracker {repo}: rate limited, resuming next tick: {error}")
            stopped = True
            break
        except (*_REPO_FAILURES, _RepoFailed) as error:
            errors += 1
            count_error()
            log(f"tracker {repo}: the tracker failed, no item pushed this tick: {error}")
            failed = True
            break
        except Exception as error:  # a host answers in its own errors; one never stops the rest
            errors += 1
            count_error()
            log(f"tracker {repo}: {item.marker}: {error}")
    if not failed:
        _write_snapshot(state_dir / f"tracker-{repo}.json", run.files)
    return PassReport(
        created=run.created,
        updated=run.updated,
        errors=errors,
        awaiting=tuple(run.awaiting),
        stopped=stopped,
        failed=failed,
    )
