"""Applies what people changed on a repo's board to the pipeline (spec: tracker-pull).

An assignment or a block holds the units that build the item, a task's done state and text reach
`tasks.md` and a task added on the board is appended to it. Every write to the planning files
goes through the pipeline's functions, which hold the change's lock."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from functools import cached_property
from pathlib import Path

from agent_build_kit import trackers
from agent_build_kit.model import Frozen
from agent_build_kit.pipeline import spans
from agent_build_kit.pipeline.task_progress import (
    TaskConflict,
    append_task,
    first_line_hash,
    mark_task,
    rewrite_task,
)
from agent_build_kit.pipeline.tracker_file import (
    ConflictRecord,
    TargetMismatch,
    TaskEntry,
    TrackerFile,
    mapping_target,
    read_for_target,
    write_tracker,
)
from agent_build_kit.pipeline.unit_store import Cause, HeldBy, StoredUnit, UnitStore
from agent_build_kit.pipeline.units import HELD, PLANNED, Unit, UnitState
from agent_build_kit.pipeline.vocabulary import FINISHED
from agent_build_kit.pipeline.work_graph import Task, read_tasks
from agent_build_kit.trackers.base import Change, Item, Tracker
from agent_build_kit.trackers.config import TrackerConfigError, TrackerSection, section_for
from agent_build_kit.trackers.field_reconcile import reconcile_field
from agent_build_kit.trackers.levels import task_key
from agent_build_kit.trackers.start_decision import covered_by, others
from agent_build_kit.trackers.wanted_board import group_state

BLOCKED = "blocked"
BLOCKED_NOTE = "group item blocked on the board"
RELEASED_NOTE = "the board no longer holds it"
REMOVED = "removed"
CLOSED_FIELD = "closed"
CLOSED_NOTE = "closed on the board; merge not recorded"
_CLOSED_EPIC = frozenset({"done", REMOVED})
_FIELDS = frozenset({"title", "body", "state", "tags"})


class ApplyConflict(Frozen):
    """A disagreement the apply step left for a person: the item, what it was about, both
    values and a note saying why."""

    item_id: str
    field: str
    spec_value: str = ""
    tracker_value: str = ""
    note: str = ""


class Applied(Frozen):
    """What an apply did not act on but kept a record of, and the conflicts it opened."""

    recorded: tuple[str, ...] = ()
    conflicts: tuple[ApplyConflict, ...] = ()


class Place(Frozen):
    """Where a board item sits in a change: its level, and its key (the change's name, a group
    key or a task key)."""

    change: str
    level: str
    key: str
    group: int | None = None


def board_state(item: Item) -> str:
    """The kit's reading of an item's state on the board: `done`, else `new`."""
    return "done" if (item.kit_state or item.state) == "done" else "new"


def board_text(item: Item, entry: TaskEntry) -> str:
    """The text a task has on the board: its body, or, when only the title was edited, the
    new title over the body last synced."""
    base_title, base_body = entry.fields.get("title", ""), entry.fields.get("body", "")
    if item.body == base_body and item.title != base_title:
        return "\n".join([item.title, *base_body.split("\n")[1:]])
    return item.body


def unmerged(where: Place, units: Sequence[Unit]) -> bool:
    """Whether the units that build the group of `where` leave it unfinished, by the rule that
    moves its item to done on the board; a group nothing builds any more is not."""
    if where.group is None:
        return False
    state, _ = group_state(where.change, where.group, units)
    return state not in ("done", "removed")


def closed_agrees(item: Item, where: Place, units: Sequence[Unit]) -> bool:
    """Whether a `closed` conflict is settled: the board no longer shows the group item done,
    or the group is no longer unmerged."""
    return board_state(item) != "done" or not unmerged(where, units)


def places_of(files: Mapping[str, TrackerFile]) -> dict[str, Place]:
    """Where each recorded item sits, by item id, over the tracker files of the changes."""
    places: dict[str, Place] = {}
    for name, found in files.items():
        if found.change:
            places[found.change.id] = Place(change=name, level="change", key=name)
        for key, entry in found.groups.items():
            group = int(key.rsplit(":", 1)[1])
            places[entry.id] = Place(change=name, level="group", key=key, group=group)
        for key, task in found.tasks.items():
            group = int(key.rsplit(":", 1)[1].split(".")[0])
            places[task.id] = Place(change=name, level="task", key=key, group=group)
    return places


def open_record(file: TrackerFile, item_id: str, field: str) -> ConflictRecord | None:
    """The open conflict of the file for the item and field."""
    return next(
        (r for r in file.conflicts if (r.item_id, r.field, r.status) == (item_id, field, "open")),
        None,
    )


def close_conflict(file: TrackerFile, item_id: str, field: str) -> TrackerFile | None:
    """The file with the open conflict for the item and field closed; None when none is open."""
    existing = open_record(file, item_id, field)
    if existing is None:
        return None
    closed = existing.model_copy(update={"status": "closed"})
    swapped = tuple(closed if r is existing else r for r in file.conflicts)
    return file.model_copy(update={"conflicts": swapped})


def gone_from_spec(tasks_path: Path, place: Place) -> bool:
    """Whether the group or task a board item stands for is no longer in `tasks.md`."""
    if place.level == "change":
        return False
    try:
        tasks = read_tasks(tasks_path, place.change)
    except (OSError, ValueError):
        return False
    if place.level == "task":
        return place.key not in {task.key for task in tasks}
    return place.group not in {task.group for task in tasks}


class _Apply:
    def __init__(
        self,
        tracker: Tracker,
        section: TrackerSection,
        changes_dir: Path,
        store: UnitStore,
        log: Callable[[str], None],
    ) -> None:
        self.tracker = tracker
        self.section = section
        self.changes_dir = changes_dir
        self.store = store
        self.log = log
        self.recorded: list[str] = []
        self.conflicts: list[ApplyConflict] = []
        self.files: dict[str, TrackerFile] = {}
        self.dirty: set[str] = set()
        self.places: dict[str, Place] = {}
        # The board change that last reached each item: who made it and when.
        self.made: dict[str, Change] = {}
        self.epics: dict[str, list[str]] = {}
        self._index()

    @cached_property
    def sync(self) -> str:
        return self.tracker.identity().name

    def _index(self) -> None:
        target = mapping_target(self.section)
        if not self.changes_dir.is_dir():
            return
        for folder in sorted(self.changes_dir.iterdir()):
            try:
                found = read_for_target(folder, self.section.kind, target)
            except (TargetMismatch, ValueError, OSError):
                continue
            if found is None:
                continue
            name = folder.name
            self.files[name] = found
            if found.epic:
                self.epics.setdefault(found.epic, []).append(name)
        self.places = places_of(self.files)

    def _tasks_path(self, change: str) -> Path:
        return self.changes_dir / change / "tasks.md"

    def _conflict(
        self,
        item_id: str,
        field: str,
        spec: str,
        board: str,
        note: str,
        change: str | None = None,
    ) -> None:
        name = change or (self.places[item_id].change if item_id in self.places else None)
        if name in self.files:
            self._record_conflict(name, item_id, field, spec, board)
        self.conflicts.append(
            ApplyConflict(
                item_id=item_id, field=field, spec_value=spec, tracker_value=board, note=note
            )
        )
        self.log(f"tracker: {item_id} {field}: {note}")

    # --- conflict records -------------------------------------------------------------------

    def _open_record(self, change: str, item_id: str, field: str) -> ConflictRecord | None:
        return open_record(self.files[change], item_id, field)

    def _record_conflict(
        self, change: str, item_id: str, field: str, spec: str, board: str
    ) -> None:
        """Record the conflict as open; one already open for the item and field keeps its
        comment and takes the new values."""
        file = self.files[change]
        existing = self._open_record(change, item_id, field)
        seen = self.made.get(item_id)
        record = ConflictRecord(
            item_id=item_id,
            field=field,
            spec_value=spec,
            tracker_value=board,
            who=seen.who if seen else "",
            when=seen.when if seen else spans.clock.now().isoformat(),
            commented=existing.commented if existing else False,
        )
        kept = tuple(r for r in file.conflicts if r is not existing)
        self.files[change] = file.model_copy(update={"conflicts": (*kept, record)})
        self.dirty.add(change)

    def _close(self, change: str, item_id: str, field: str) -> None:
        """Close the open conflict for the item and field: the two sides agree again."""
        closed = close_conflict(self.files[change], item_id, field)
        if closed is None:
            return
        self.files[change] = closed
        self.dirty.add(change)

    def surface(self) -> None:
        """Comment once on the item of each open conflict not yet commented."""
        for change, file in list(self.files.items()):
            for record in file.conflicts:
                if record.status != "open" or record.commented:
                    continue
                text = (
                    f"The kit left a conflict on {record.field} for a person to settle: "
                    f"the spec has {record.spec_value!r}, the board has {record.tracker_value!r}."
                )
                try:
                    self.tracker.comment(record.item_id, text)
                except Exception as error:  # noqa: BLE001 — a host answers in its own errors
                    self.log(f"tracker: no comment on {record.item_id}: {error}")
                    continue
                current = self.files[change]
                marked = tuple(
                    r.model_copy(update={"commented": True}) if r is record else r
                    for r in current.conflicts
                )
                self.files[change] = current.model_copy(update={"conflicts": marked})
                self.dirty.add(change)

    # --- removals, titles and the epic ------------------------------------------------------

    def epic(self, changes: Sequence[str], item: Item) -> None:
        """The manual epic is a person's: nothing is applied, and a closed or removed one is
        warned about once for each change that names it."""
        closed = (item.kit_state or item.state) in _CLOSED_EPIC
        for change in changes:
            file = self.files[change]
            if closed and not file.epic_warned:
                self.log(
                    f"tracker: epic {item.id} of change {change} is closed or removed on the board"
                )
            if closed != file.epic_warned:
                self.files[change] = file.model_copy(update={"epic_warned": closed})
                self.dirty.add(change)

    def removal(self, where: Place, item: Item) -> bool:
        """Whether the item is removed on the board: that is a conflict for a person, and
        restoring the item closes it."""
        if (item.kit_state or item.state) != REMOVED:
            self._close(where.change, item.id, REMOVED)
            return False
        self._conflict(item.id, REMOVED, "", REMOVED, "removed on the board; the spec is kept")
        return True

    def _gone_from_spec(self, where: Place) -> bool:
        """Whether the group or task a board item stands for is no longer in `tasks.md`."""
        return gone_from_spec(self._tasks_path(where.change), where)

    def settle(self) -> None:
        """Close the open conflicts whose two sides agree again without a board change to show
        it: the outbound pass put the spec's title back, or the person took the removed task out
        of the spec."""
        for change, file in list(self.files.items()):
            for record in file.conflicts:
                if record.status != "open" or record.field not in ("title", REMOVED, CLOSED_FIELD):
                    continue
                try:
                    item = self.tracker.get(record.item_id)
                except Exception as error:  # noqa: BLE001 — a host answers in its own errors
                    self.log(f"tracker: the board was not read for {record.item_id}: {error}")
                    continue
                where = self.places.get(record.item_id)
                if record.field == "title":
                    agreed = item.title == record.spec_value
                elif record.field == CLOSED_FIELD:
                    agreed = where is None or closed_agrees(item, where, self.store.all())
                else:
                    agreed = (item.kit_state or item.state) != REMOVED or (
                        where is not None and self._gone_from_spec(where)
                    )
                if agreed:
                    self._close(change, record.item_id, record.field)

    def _unmerged(self, where: Place) -> bool:
        return unmerged(where, self.store.all())

    def closed(self, where: Place, item: Item) -> None:
        """A group item closed on the board is not a merge: while its unit is not recorded
        merged it is a conflict for a person, and the unit is left as it is."""
        if where.level != "group":
            return
        if board_state(item) == "done" and self._unmerged(where):
            self._conflict(item.id, CLOSED_FIELD, "not merged", "done", CLOSED_NOTE)
        else:
            self._close(where.change, item.id, CLOSED_FIELD)

    def title(self, where: Place, item: Item) -> None:
        """A change or group item retitled on the board keeps the spec's title: the edit is a
        conflict and the recorded copy is the board's, so the outbound pass pushes the spec's.
        An adopted item keeps the board's wording instead, with no conflict."""
        file = self.files[where.change]
        entry = file.change if where.level == "change" else file.groups.get(where.key)
        if entry is None:
            return
        open_record = self._open_record(where.change, item.id, "title")
        spec = open_record.spec_value if open_record else entry.fields.get("title", "")
        if item.title == spec:
            self._close(where.change, item.id, "title")
            return
        if not entry.adopted:  # an adopted item keeps the board's wording: no conflict
            self._conflict(
                item.id, "title", spec, item.title, "edited on the board; the spec's wins"
            )
        moved = entry.model_copy(
            update={"fields": {**entry.fields, "title": item.title}, "revision": item.revision}
        )
        current = self.files[where.change]
        self.dirty.add(where.change)
        if where.level == "change":
            self.files[where.change] = current.model_copy(update={"change": moved})
        else:
            groups = {**current.groups, where.key: moved}
            self.files[where.change] = current.model_copy(update={"groups": groups})

    # --- holds ------------------------------------------------------------------------------

    def _reason(self, unit: StoredUnit) -> str:
        """Why the board holds `unit`: a person on, or a block on, an item it covers (read once
        each, by the same rule as the claim gate); empty when nothing does."""
        try:
            covered = covered_by(unit, self.section, self.changes_dir)
        except TargetMismatch:
            return ""
        if covered is None:
            return ""
        people: list[str] = []
        blocked = False
        for item_id in dict.fromkeys(covered[0]):
            item = self.tracker.get(item_id)
            blocked = blocked or (
                item.kind == "group" and (item.kit_state or item.state) == BLOCKED
            )
            people.extend(who for who in others(item, self.sync) if who not in people)
        if people:
            return f"assigned to {', '.join(people)}"
        return BLOCKED_NOTE if blocked else ""

    def holds(self, change: str, groups: set[int], done: set[str]) -> None:
        """Hold or release each unit not yet in `done` that builds one of `groups` of `change`."""
        for unit in self.store.all():
            covered = {g for m in unit.members() if m.change == change for g in m.groups}
            if unit.id in done or not covered & groups:
                continue
            done.add(unit.id)
            try:
                reason = self._reason(unit)
            except Exception as error:  # noqa: BLE001 — a host answers in its own errors
                self.log(f"tracker: the board was not read for {unit.id}: {error}")
                continue
            if unit.state in FINISHED:
                if reason:
                    self.recorded.append(f"{unit.id} is {unit.state}: {reason} not applied")
            elif reason and unit.state != HELD:
                self.store.set_state(
                    unit.id, HELD, note=reason, held_by=HeldBy.BOARD, cause=Cause.NEEDS_HUMAN
                )
            elif not reason and unit.state == HELD and unit.held_by == HeldBy.BOARD:
                back = UnitState.IN_REVIEW if unit.pr else PLANNED
                self.store.set_state(unit.id, back, note=RELEASED_NOTE, cause=Cause.RELEASED)

    # --- tasks ------------------------------------------------------------------------------

    def _update_entry(self, change: str, key: str, **changes: object) -> None:
        file = self.files[change]
        entry = file.tasks[key]
        fields = {**entry.fields, **{k: str(v) for k, v in changes.items() if k in _FIELDS}}
        update = {k: v for k, v in changes.items() if k not in _FIELDS}
        self.files[change] = file.model_copy(
            update={
                "tasks": {**file.tasks, key: entry.model_copy(update={"fields": fields, **update})}
            }
        )
        self.dirty.add(change)

    def task(self, where: Place, item: Item) -> None:
        change, key = where.change, where.key
        entry = self.files[change].tasks[key]
        path = self._tasks_path(change)
        current = next((t for t in read_tasks(path, change) if t.key == key), None)
        if current is None:
            return
        self._state(item, entry, current, path, where)
        self._text(item, entry, current, path, where)

    def _state(self, item: Item, entry: TaskEntry, current: Task, path: Path, where: Place) -> None:
        board = board_state(item)
        base = entry.fields.get("state", "")
        spec = "done" if current.done else "new"
        outcome = reconcile_field("state", base, spec, board, spec_who="spec", tracker_who="board")
        if outcome.action != "tracker":
            self._close(where.change, item.id, "state")
            return
        try:
            mark_task(path, where.key, done=board == "done", text_hash=entry.text_hash)
        except TaskConflict as error:
            self._conflict(item.id, "state", spec, board, str(error))
            return
        self._close(where.change, item.id, "state")
        self._update_entry(where.change, where.key, state=board, revision=item.revision)

    def _text(self, item: Item, entry: TaskEntry, current: Task, path: Path, where: Place) -> None:
        base_body = entry.fields.get("body", "")
        board = board_text(item, entry)
        outcome = reconcile_field(
            "body", base_body, current.text, board, spec_who="spec", tracker_who="board"
        )
        if outcome.conflict is not None:
            self._conflict(
                item.id, "body", current.text, board, "edited in the spec and on the board"
            )
            return
        self._close(where.change, item.id, "body")
        if outcome.action != "tracker":
            return
        try:
            stored = rewrite_task(
                path, where.key, text=board, text_hash=first_line_hash(current.text)
            )
        except (TaskConflict, ValueError) as error:
            self._conflict(item.id, "body", current.text, board, str(error))
            return
        self._update_entry(
            where.change,
            where.key,
            title=stored.split("\n", 1)[0],
            body=stored,
            revision=item.revision,
            text_hash=first_line_hash(stored),
        )
        self.recorded.append(f"{where.key} text rewritten from the board; a replan may follow")

    # --- new items --------------------------------------------------------------------------

    def added(self, item: Item) -> None:
        parent = self.places.get(item.parent_id or "")
        if parent is None or item.kind != "task":
            return
        if "task" not in self.section.levels:
            self._conflict(
                item.id, "item", "", item.title, "it has no level to join", parent.change
            )
            return
        if parent.level == "change" and "group" in self.section.levels:
            self._conflict(
                item.id, "item", "", item.title, "it has no group item to join", parent.change
            )
            return
        change = parent.change
        path = self._tasks_path(change)
        text = item.title if not item.body else f"{item.title}\n{item.body}"
        try:
            group = self._lowest_group(change, parent, path)
            number, stored = append_task(path, change, group, text)
        except ValueError as error:
            self._conflict(item.id, "item", "", item.title, str(error), change)
            return
        key = task_key(change, group, number)
        file = self.files[change]
        # The base is what the board holds, so the next outbound pass pushes the spec's text.
        entry = TaskEntry(
            id=item.id,
            fields={
                "title": item.title,
                "body": item.body,
                "state": board_state(item),
                "tags": "",
            },
            revision=item.revision,
            text_hash=first_line_hash(stored),
        )
        self.files[change] = file.model_copy(update={"tasks": {**file.tasks, key: entry}})
        self.places[item.id] = Place(change=change, level="task", key=key, group=group)
        self.dirty.add(change)
        self.recorded.append(f"{key} added from the board; a replan may follow")

    def _lowest_group(self, change: str, parent: Place, path: Path) -> int:
        covered = [
            g
            for unit in self.store.all()
            if unit.state not in FINISHED
            for m in unit.members()
            if m.change == change and (parent.group is None or parent.group in m.groups)
            for g in m.groups
        ]
        if covered:
            return min(covered)
        if parent.group is not None:
            return parent.group
        return min(task.group for task in read_tasks(path, change))

    def save(self) -> None:
        for change in sorted(self.dirty):
            write_tracker(self.changes_dir / change, self.files[change])
        self.dirty.clear()


def apply_changes(
    repo: str,
    changes: Sequence[Change],
    *,
    changes_dir: Path,
    store: UnitStore,
    log: Callable[[str], None] = print,
) -> Applied:
    """Hold or release units, tick or untick boxes, rewrite task lines and append tasks for the
    board changes `changes` of `repo`, writing the planning files only through the pipeline.

    A failure on one item or unit is logged and leaves the others to run; the tracker files are
    always saved after the item edits, before the holds are read."""
    try:
        section = section_for(repo)
        tracker = trackers.for_repo(repo) if section is not None else None
    except TrackerConfigError as error:
        log(f"tracker {repo}: apply skipped: {error}")
        return Applied()
    if section is None or tracker is None:
        return Applied()
    run = _Apply(tracker, section, changes_dir, store, log)
    touched: dict[str, set[int]] = {}
    seen: set[str] = set()
    try:
        for change in changes:
            if change.item_id in seen:
                continue
            seen.add(change.item_id)
            run.made[change.item_id] = change
            try:
                item = tracker.get(change.item_id)
                if item.id in run.epics:
                    run.epic(run.epics[item.id], item)
                    continue
                where = run.places.get(item.id)
                if where is None:
                    run.added(item)
                elif run.removal(where, item):
                    continue
                elif where.level == "task":
                    run.task(where, item)
                else:
                    run.title(where, item)
                    run.closed(where, item)
            except Exception as error:  # noqa: BLE001 — a host answers in its own errors
                log(f"tracker {repo}: item {change.item_id} not applied: {error}")
                continue
            if where is not None and where.group is not None:
                touched.setdefault(where.change, set()).add(where.group)
    finally:
        run.settle()
        run.surface()
        run.save()
    held: set[str] = set()
    for name, groups in touched.items():
        run.holds(name, groups, held)
    return Applied(recorded=tuple(run.recorded), conflicts=tuple(run.conflicts))
