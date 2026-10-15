"""Units and their state, kept in the planning repo.

Tracking lives here rather than in GitHub issues (docs/architecture.md). One
file, versioned beside the specs, easy to reset, and it leaves no debris in
the code repos when a change is re-planned or abandoned. A
GitHub backend still exists in `issues.py` for when the units should be
visible next to the PRs, but it is opt-in.

What that costs: nothing closes a unit when its PR merges, so the runner and
the poller have to record state themselves. That makes two properties matter
more than anything else here —

- **a reload sees what the last process wrote**, since each scheduler tick is
  a new process, and
- **re-planning never loses progress.** The planner proposes shape, not
  history; a re-planned unit keeps its state, branch and PR, or the pipeline
  would cheerfully rebuild work that has already merged.
"""

from __future__ import annotations

import functools
import json
import time
from collections.abc import Callable, Collection, Sequence
from contextlib import AbstractContextManager
from datetime import datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any

from pydantic import Field, ValidationError, field_validator, model_validator

from agent_build_kit.budget import cut_head
from agent_build_kit.model import Frozen
from agent_build_kit.pipeline import spans
from agent_build_kit.pipeline.file_lock import atomic_write_text, file_lock
from agent_build_kit.pipeline.units import (
    FAILED,
    HELD,
    IN_REVIEW,
    PLANNED,
    RUNNING,
    Join,
    Member,
    Priority,
    Unit,
    UnitState,
)
from agent_build_kit.pipeline.work_graph import FLAGS
from agent_build_kit.redaction import redact_text

# A unit that the latest plan no longer contains. Kept rather than deleted: it
# may already have an open PR, and the runner needs to see that the plan moved.
UNPLANNED = UnitState.UNPLANNED


class HeldBy(StrEnum):
    """Why a unit is held: `REVIEWER` (the hold label), `REVIEW` (the review
    loop), `DEPTH` (the stack depth cap) or `TOOLCHAIN`; `NONE` when it is not
    held, and in a record written before this was kept."""

    NONE = ""
    REVIEWER = "reviewer"
    REVIEW = "review"
    DEPTH = "depth"
    TOOLCHAIN = "toolchain"


class Cause(StrEnum):
    """Why a unit's state last changed out of running; what the pass, the
    readmission rule and the diagram decide from. A record written before
    causes were kept has none."""

    REWORK = "rework"
    BASE_CHANGED = "base_changed"
    UPSTREAM_WENT_BACK = "upstream_went_back"
    USAGE = "usage"
    DEPTH = "depth"
    TOOLCHAIN = "toolchain"
    REVIEW_ESCALATED_CLASS = "review_escalated_class"
    REVIEW_ESCALATED_DISAGREEMENT = "review_escalated_disagreement"
    NEEDS_HUMAN = "needs_human"
    REVIEWER_HOLD = "reviewer_hold"
    REQUEUED = "requeued"
    GATED = "gated"
    RELEASED = "released"
    RESTACK_CONFLICT = "restack_conflict"
    RESTACK_DEFERRED = "restack_deferred"
    DIRTY_WORKTREE = "dirty_worktree"
    ATTACHED = "attached"
    ADOPTED = "adopted"
    MERGED = "merged"
    CLOSED = "closed"
    FAILED = "failed"
    HOST_UNAVAILABLE = "host_unavailable"
    NETWORK_UNAVAILABLE = "network_unavailable"
    SERVICE_UNAVAILABLE = "service_unavailable"
    ENVIRONMENT = "environment"
    SPLIT_HELD = "split_held"


class RequeueReason(StrEnum):
    """Why a unit was requeued: what the requeue handling depends on, whatever
    the display text says."""

    RESTART = "restart"
    RELEASED = "released"
    RESUME = "resume"
    FROM_FAILURE = "from_failure"


class ReworkKind(StrEnum):
    """What sent a unit back for rework, which picks the feedback it is given."""

    FAILING_CHECKS = "failing_checks"
    CONFLICT = "conflict"
    LABEL = "label"
    CHANGES_REQUESTED = "changes_requested"
    COMMENT = "comment"


class FeedbackSource(StrEnum):
    """Where a unit's saved feedback came from, which picks the prompt it is
    given; `NONE` when there is none."""

    NONE = ""
    REVIEW = "review"
    CI = "ci"
    CONFLICT = "conflict"
    TIER1 = "tier1"
    TIER2 = "tier2"


def feedback_source_of(rework: ReworkKind | None) -> FeedbackSource:
    """Where a rework's feedback comes from, by the kind that sent the unit back."""
    if rework is ReworkKind.FAILING_CHECKS:
        return FeedbackSource.CI
    if rework is ReworkKind.CONFLICT:
        return FeedbackSource.CONFLICT
    if rework is None:
        return FeedbackSource.NONE
    return FeedbackSource.REVIEW


def corrupt_store_message(path: Path) -> str:
    return f"unit store at {path} could not be read"


class Description(Frozen):
    """What the reviewer says an approved branch does: a summary and its core changes."""

    summary: str = ""
    changes: tuple[str, ...] = ()


class ClosePending(Frozen):
    """A satisfied unit's pull request that is still to be closed: its number and the
    reason to post on it."""

    pr: int
    reason: str


class StoredUnit(Unit):
    """A unit plus what has happened to it."""

    branch: str = ""
    pr: int | None = None
    # The pull request's changed lines as the reviewer sees them, generated
    # files left out; None until it has a pull request.
    actual_lines: int | None = None
    # The flag of the first flagged group the unit carries, empty when none, and its
    # estimate times its kind's calibration ratio when it was planned (see
    # `unit_size.calibration`); None for a record from before they were kept, or with
    # calibration off.
    flag: str = ""
    calibrated_lines: Annotated[int, Field(strict=True, gt=0)] | None = None
    # The SHA this runner last published for `branch`. The next push leases
    # against exactly this, so it has to outlive the process that pushed it.
    pushed: str | None = None
    # When `pushed` was recorded; None for a store written before this field.
    pushed_at: datetime | None = None
    # The head commit `check_reruns` counts for, and how many times its cancelled
    # checks have been re-run. Here because each poll is a new process.
    check_rerun_head: str = ""
    check_reruns: int = 0
    # The base tip a conflict attempt was made at, the head the unit had pushed when it
    # started, how many attempts there have been at that tip, and when the last started.
    conflict_tip: str = ""
    conflict_head: str = ""
    conflict_attempts: int = 0
    conflict_at: datetime | None = None
    # What review asked for, waiting to be addressed. Cleared once a run has
    # acted on it, so a unit is never reworked twice for the same comment.
    feedback: str = ""
    # What a person asked for with `abk requeue --note`, shown ahead of `feedback`
    # in the next prompt and cleared where the rework commit is made.
    guidance: str = ""
    # The commit the review loop last approved. Nothing else may be pushed:
    # see the gate before the `push` node. Here, not in the run, because the
    # push gate and `build_restack` read and write it with no run in progress.
    approved: str = ""
    # What the reviewer said the approved branch does, shown in the pull
    # request description; None until an approval carried one.
    description: Description | None = None
    # Whether `feedback` is a person's words, fetched from the pull request when
    # it was requeued, as opposed to anything the pipeline or the host wrote.
    # Set only with the feedback (see `set_feedback`), so it never outlives it.
    feedback_from_person: bool = False
    # Where `feedback` came from (see `FeedbackSource`).
    feedback_source: FeedbackSource = FeedbackSource.NONE
    # Set when the unit was moved onto a predecessor that changed under it,
    # for the reviewer: which files needed resolving, or how its tests were
    # carried over. Cleared once the unit is back in review. Here, not in the
    # run, because `build_restack` writes it with no run in progress.
    predecessor_note: str = ""
    # The file name of this unit's most recent run log (see `run_log`); empty
    # until it has run.
    run_log: str = ""
    # Where this unit's most recent run is in the traces (`telemetry.reference`),
    # so a later run links back to it; empty until a run has been traced.
    trace: str = ""
    # Why the host last refused to register this unit's pull request in a
    # stack; empty when it did, or was never asked. Advisory: nothing reads it
    # to decide anything.
    stack_refusal: str = ""
    # Why the unit is held (see `HeldBy`).
    held_by: HeldBy = HeldBy.NONE
    # The branch a unit held for depth is still on.
    held_base: str = ""
    # How a requeue that found a dependency it waits on unmet is delivered once
    # it is met (see `Cause.GATED`); None when no requeue is waiting.
    gated_requeue: RequeueReason | None = None
    # What a unit held for `Cause.SPLIT_HELD` waits on: the splits its tier 2 run
    # parked, the commit that run passed on and the snapshot it posted.
    parked_splits: list[str] = []
    parked_sha: str = ""
    parked_snapshot: str = ""
    # The close of a satisfied unit's pull request, kept until it is done.
    close_pending: ClosePending | None = None
    # The step the unit last stopped in, and how many times in a row the code host
    # being unavailable has parked it; a success resets the count.
    step: str = ""
    parked_attempts: int = 0
    # How many times in a row the model service's status has parked it.
    service_attempts: int = 0
    history: tuple[dict, ...] = ()
    # When the unit was first evaluated with nothing blocking it, and when a
    # person first answered its pull request; None until then.
    ready_at: datetime | None = None
    first_human_activity_at: datetime | None = None

    @field_validator("flag")
    @classmethod
    def _known_flag(cls, flag: str) -> str:
        if flag and flag not in FLAGS:
            raise ValueError(f"flag must be one of {', '.join(FLAGS)} or empty, not {flag!r}")
        return flag

    @property
    def unstarted(self) -> bool:
        """Planned, with no branch, commit or pull request:
        nothing exists that removing or extending this unit could disturb."""
        return self.state == PLANNED and not (
            self.branch or self.pr is not None or self.pushed or self.approved
        )

    @property
    def started_at(self) -> datetime | None:
        """When the unit first ran, read from its history."""
        return self._first_entry(RUNNING)

    @property
    def review_requested_at(self) -> datetime | None:
        """When the unit first entered review, read from its history."""
        return self._first_entry(IN_REVIEW)

    def _first_entry(self, state: str) -> datetime | None:
        for entry in self.history:
            if entry.get("state") == state:
                try:
                    return datetime.fromisoformat(str(entry.get("at", "")))
                except ValueError:
                    continue
        return None

    @property
    def note(self) -> str:
        """Why the unit is in its present state, as its latest history entry says."""
        return str(self.history[-1].get("note", "")) if self.history else ""

    def is_new_conflict(self, since: datetime) -> bool:
        """Whether the conflict that began at `since` is not the one the recorded attempts
        were made for: none recorded, or the run of conflicting answers began after them."""
        return self.conflict_at is None or since > self.conflict_at

    def attempts_spent(self, max_rounds: int) -> bool:
        """Whether the attempts recorded for the current conflict are all there will be: the
        last left the head as it was, or `max_rounds` have been made. Said of one base tip;
        a new tip starts the count again."""
        return self.conflict_attempts >= max_rounds or (self.pushed or "") == self.conflict_head

    @property
    def held_by_the_label(self) -> bool:
        """Held, and by a reviewer's hold label. A record from before the holder was
        kept has none, and is not read to say so from its note."""
        return self.state == HELD and self.held_by == HeldBy.REVIEWER

    @property
    def cause(self) -> Cause | None:
        """Why the unit's state last changed, or `None` for a record from before
        causes were kept."""
        if not self.history or not self.history[-1].get("cause"):
            return None
        try:
            return Cause(_OLDER_CAUSES.get(self.history[-1]["cause"], self.history[-1]["cause"]))
        except ValueError:
            # Written by a newer release; read as a record from before causes were kept.
            return None

    @model_validator(mode="before")
    @classmethod
    def _tolerate_other_releases(cls, data: Any) -> Any:
        """Drop what another release left empty; refuse what it left a value in.

        An old-engine field written empty, and a key no field of this release names
        when its value is empty, carry nothing, so the next write omits them. A valued
        one is information this release cannot keep. Works on a copy, so the dict the
        caller handed in is left as it was. It applies to every construction, so a
        misspelled keyword given an empty value in code is dropped too.
        """
        if not isinstance(data, dict):
            return data
        item = {k: v for k, v in data.items() if k not in REMOVED_FIELDS}
        for old, new in _OLDER_FIELDS.items():
            if old in item:
                item[new] = item.get(new) or item[old]
                del item[old]
        unit_id = item.get("id", "?")
        for field in OLD_ENGINE_FIELDS:
            if field in item and item[field] == _WRITTEN_EMPTY.get(field):
                del item[field]
        for field in OLD_ENGINE_FIELDS:
            if field in item:
                raise ValueError(
                    f"{unit_id}: the units store holds `{field}`, a field of the "
                    "previous engine; finish or requeue that unit's work with the release that "
                    "wrote it, then remove the field"
                )
        for key in [key for key in item if key not in cls.model_fields]:
            value = item[key]
            # `0 == False` in Python, so emptiness is tested by type, not truthiness.
            if (
                value is None
                or value is False
                or (isinstance(value, (str, list, dict)) and not value)
            ):
                del item[key]
            else:
                raise ValueError(
                    f"{unit_id}: the units store holds `{key}` = {value!r}, "
                    "a field this release does not know; a newer release wrote it, so update "
                    "this checkout to that release"
                )
        return item


# Fields an earlier release wrote that no longer exist, dropped whatever their value.
# `merge_before` was the merge gate, removed when a `Needs` dependency began to start on
# its parent's branch; the next write leaves the key out.
REMOVED_FIELDS = ("merge_before",)

# Names an earlier release wrote for what is now a split: the field of parked runtimes, and the
# cause a unit parked on one carried. Read as the new names; only the new ones are written.
_OLDER_FIELDS = {"parked_runtimes": "parked_splits"}
_OLDER_CAUSES = {"runtime_blocked": "split_held"}

# The in-run fields a unit carried before its progress moved into its thread. A store
# that still holds one is refused: that work must be finished or requeued first.
OLD_ENGINE_FIELDS = (
    "review_rounds",
    "deferred",
    "pending_replies",
    "person_comments",
    "resume_from",
    "classic_run",
)

# The previous release wrote these on every unit, empty when no run was in progress.
# An empty one is dropped on read; only a value in it is old work.
_WRITTEN_EMPTY = {"resume_from": "", "classic_run": {}}


# The text fields of a record a rewrite of its words may change (see `UnitStore.rewrite_text`).
REWRITTEN_TEXT_FIELDS = ("feedback", "guidance", "predecessor_note", "stack_refusal")

StateChanged = Callable[[StoredUnit, list[StoredUnit], bool], None]


def _exclusive(method):
    """One change to the store at a time.

    Every change reads the whole file, edits it and writes it back, so two
    units building in parallel could each read, and the second write would
    drop the first's change — a unit's state, or the SHA a push leases on.
    """

    @functools.wraps(method)
    def locked(self: UnitStore, *args, **kwargs):
        with self.locked():
            return method(self, *args, **kwargs)

    return locked


def with_text(unit: StoredUnit, fn: Callable[[str], str]) -> StoredUnit:
    """The record with `fn` applied to its free text (`REWRITTEN_TEXT_FIELDS` and each history
    note); identifiers, state and timestamps are kept."""
    return unit.model_copy(
        update={
            **{field: fn(getattr(unit, field)) for field in REWRITTEN_TEXT_FIELDS},
            "history": tuple(
                {**entry, "note": fn(entry["note"])}
                if isinstance(entry.get("note"), str)
                else entry
                for entry in unit.history
            ),
        }
    )


def guidance_excerpt(note: str) -> str:
    """What a history entry says of a person's note: its first 200 characters, or nothing."""
    return f" — {cut_head(note, 200, 'char')}" if note else ""


class UnitStore:
    """The planning repo's record of every unit, across all repos."""

    def __init__(
        self,
        path: Path,
        *,
        on_write: Callable[[list[StoredUnit]], None] | None = None,
        on_state: StateChanged | None = None,
    ) -> None:
        """`on_write` sees every unit after each change — how the diagram stays
        current without every call site that changes a state remembering it.

        `on_state` hears each `set_state` once the change is written and the
        store unlocked, with the unit, every unit, and whether this call is
        what first recorded its pull request. How a pull request's labels
        follow its unit, again without each call site remembering."""
        self.path = path
        self.on_write = on_write
        self.on_state = on_state

    def locked(self) -> AbstractContextManager[None]:
        """The lock every change to the store is made under, for a rewrite of the file
        that is not a change to a unit."""
        return file_lock(self.path.with_name(f"{self.path.name}.lock"))

    def _read(self) -> dict[str, StoredUnit]:
        if not self.path.exists():
            return {}

        try:
            raw = json.loads(self.path.read_text())
            units = raw["units"]
        except (OSError, ValueError, KeyError, TypeError) as error:
            # Unlike a cache, this is the source of truth: treating an
            # unreadable file as "nothing planned" would re-plan and rebuild
            # work that has already merged.
            raise ValueError(f"{corrupt_store_message(self.path)}: {error}") from error

        stored: dict[str, StoredUnit] = {}
        for item in units:
            # Validated rather than splatted in: the file is on disk and may
            # predate a change to StoredUnit, so a missing or unknown key
            # should fail here — naming the field — rather than construct
            # something odd that breaks three steps later.
            try:
                unit = StoredUnit.model_validate(item)
            except ValidationError as error:
                raise ValueError(f"{corrupt_store_message(self.path)}: {error}") from error
            stored[unit.id] = unit
        return stored

    def _write(self, stored: dict[str, StoredUnit]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # mode="json" so tuples land as JSON arrays and datetimes as strings,
        # which is what `model_validate` reads back on the next tick.
        payload = {"units": [_record(unit) for unit in stored.values()]}
        # Indented and one key per line: this file is committed, so it turns up
        # in diffs and reviews, where dense JSON is unreadable.
        # Written aside and renamed into place: reads are not locked, and a
        # reader catching a half-written file would take it for corruption.
        atomic_write_text(self.path, json.dumps(payload, indent=2) + "\n")
        if self.on_write:
            self.on_write(list(stored.values()))

    def all(self) -> list[StoredUnit]:
        return list(self._read().values())

    def get(self, unit_id: str) -> StoredUnit:
        return self._read()[unit_id]

    def history(self, unit_id: str) -> list[dict]:
        return list(self.get(unit_id).history)

    @_exclusive
    def upsert(self, units: Sequence[Unit], *, change: str | None = None) -> None:
        """Merge a freshly planned graph into the store.

        Shape comes from the plan; state, branch and PR come from what is
        already recorded. A unit the plan no longer contains is marked
        `unplanned` rather than deleted — it may already have an open PR.
        """
        stored = self._read()
        planned_ids = {unit.id for unit in units}

        for unit in units:
            existing = stored.get(unit.id)
            # Only the planned shape: `StoredUnit` is a `Unit`, so a caller
            # may hand back what `all()` returned, and those extra fields
            # would collide with the recorded ones set just below.
            fresh = StoredUnit(
                **unit.model_dump(include=set(Unit.model_fields)),
                branch=existing.branch if existing else "",
                pr=existing.pr if existing else None,
                pushed=existing.pushed if existing else None,
                pushed_at=existing.pushed_at if existing else None,
                actual_lines=existing.actual_lines if existing else None,
                flag=existing.flag if existing else "",
                calibrated_lines=existing.calibrated_lines if existing else None,
                check_rerun_head=existing.check_rerun_head if existing else "",
                check_reruns=existing.check_reruns if existing else 0,
                conflict_tip=existing.conflict_tip if existing else "",
                conflict_head=existing.conflict_head if existing else "",
                conflict_attempts=existing.conflict_attempts if existing else 0,
                conflict_at=existing.conflict_at if existing else None,
                # Work in progress, not shape: a re-plan must not drop what
                # review asked for, or where a paused unit should pick up.
                feedback=existing.feedback if existing else "",
                approved=existing.approved if existing else "",
                description=existing.description if existing else None,
                feedback_from_person=existing.feedback_from_person if existing else False,
                feedback_source=existing.feedback_source if existing else FeedbackSource.NONE,
                predecessor_note=existing.predecessor_note if existing else "",
                run_log=existing.run_log if existing else "",
                trace=existing.trace if existing else "",
                stack_refusal=existing.stack_refusal if existing else "",
                held_by=existing.held_by if existing else HeldBy.NONE,
                held_base=existing.held_base if existing else "",
                history=existing.history if existing else ({"state": PLANNED, "at": _now()},),
            )
            if existing and not existing.unstarted:
                # A unit keeps the priority, the project and the review tier it started with.
                fresh = fresh.model_copy(
                    update={
                        "priority": existing.priority,
                        "project": existing.project,
                        "review_tier": existing.review_tier,
                    }
                )
            if existing and existing.joined and not fresh.joined:
                # Groups of other changes it took in are not in the plan the
                # planner re-derives for this change, and are not its to drop.
                # Its estimate too: the plan sizes only the unit's own groups,
                # and a later join is checked against what the unit now holds.
                fresh = fresh.model_copy(
                    update={
                        "joined": existing.joined,
                        "estimated_lines": existing.estimated_lines,
                    }
                )
            if existing:
                # Carry progress over — a running, open or merged unit is not
                # rebuilt just because the graph was re-derived. The exception
                # is `unplanned`: the plan is asking for this unit again, and
                # keeping the demotion meant `ready_units`, which only picks
                # `planned`, could never build it — nor anything depending on
                # it, which stalls every unit behind it.
                if existing.state == UNPLANNED:
                    fresh = _with_state(fresh, PLANNED)
                else:
                    fresh = fresh.model_copy(update={"state": existing.state})
            stored[unit.id] = fresh

        if change is not None:
            for unit_id, unit in stored.items():
                # Only a unit that never started can be dropped — that is the
                # whole set this mechanism was ever for. Anything else is
                # absent from the plan for a reason that is not "no longer
                # wanted": the planner is told about in-flight units as
                # context precisely so it stops proposing them, and a merged
                # unit is history whose work is already in main.
                #
                # Demoting on absence breaks both: a unit demoted to
                # `unplanned` after merging makes its change unarchivable, and
                # one demoted while its PR is open blocks every unit behind it.
                if unit.state != PLANNED:
                    continue
                if unit.change == change and unit_id not in planned_ids:
                    stored[unit_id] = _with_state(unit, UNPLANNED)

        self._write(stored)

    @_exclusive
    def import_units(self, units: Sequence[StoredUnit]) -> None:
        """Add records from another store with every field kept; an equal one is skipped and a
        differing one with the same id is a conflict naming the id, with nothing written."""
        stored = self._read()
        added = {unit.id: unit for unit in units if unit.id not in stored}
        if conflicts := [u.id for u in units if u.id in stored and stored[u.id] != u]:
            raise ValueError(f"{self.path} holds a different record for {', '.join(conflicts)}")
        if added:
            self._write({**stored, **added})

    @_exclusive
    def rewrite_text(self, fn: Callable[[str], str]) -> list[str]:
        """Apply `fn` to the text fields of every record (the feedback, guidance, predecessor
        note, stack refusal and each history note), write once, and return the ids changed.
        Nothing is written when no text changed; no other field or timestamp is touched."""
        stored = self._read()
        changed = []
        for uid, unit in stored.items():
            rewritten = with_text(unit, fn)
            if rewritten != unit:
                stored[uid] = rewritten
                changed.append(uid)
        if changed:
            self._write(stored)
        return changed

    @_exclusive
    def remove_units(self, unit_ids: Collection[str]) -> None:
        """Remove the records with these ids."""
        stored = self._read()
        kept = {uid: unit for uid, unit in stored.items() if uid not in unit_ids}
        if len(kept) != len(stored):
            self._write(kept)

    def unplan_vanished(self, changes: Collection[str]) -> list[str]:
        """Mark `unplanned` each unit that never started whose change is not among `changes`
        (the changes that exist), and return their ids. A started unit is left as it is."""
        stored = self._read()
        dropped = [
            unit_id
            for unit_id, unit in stored.items()
            if unit.state == PLANNED and unit.unstarted and unit.change not in changes
        ]
        for unit_id in dropped:
            stored[unit_id] = _with_state(stored[unit_id], UNPLANNED)
        if dropped:
            self._write(stored)
        return dropped

    @_exclusive
    def join(self, join: Join) -> tuple[int, int] | None:
        """Apply a planned join, or return `None` and change nothing.

        Both units are read again here, because either may have started since
        the plan was made. On success the units' estimates before and after
        are returned, `onto` carries the work, a unit joined in is removed and
        whatever depended on it depends on `onto`.
        """
        stored = self._read()
        onto = stored.get(join.onto)
        taken = stored.get(join.unit) if join.unit else None
        if onto is None or not onto.unstarted:
            return None
        if join.unit and (taken is None or not taken.unstarted):
            return None

        if taken is not None:
            members, added = taken.members(), taken.estimated_lines
        else:
            members, added = (Member(change=join.change, groups=join.groups),), join.estimated_lines
        before = onto.estimated_lines
        grown = onto.taking(members, estimated_lines=added)
        stored[onto.id] = grown.model_copy(
            update={
                "history": (*onto.history, {"state": onto.state, "at": _now(), "note": "joined"})
            }
        )
        if taken is not None:
            del stored[taken.id]
            for unit_id, unit in stored.items():
                if taken.id in unit.depends_on:
                    repointed = (onto.id if dep == taken.id else dep for dep in unit.depends_on)
                    stored[unit_id] = unit.model_copy(
                        update={"depends_on": tuple(dict.fromkeys(repointed))}
                    )
        self._write(stored)
        return before, before + added

    def set_state(
        self,
        unit_id: str,
        state: UnitState,
        *,
        pr: int | None = None,
        branch: str | None = None,
        note: str = "",
        held_by: HeldBy = HeldBy.NONE,
        cause: Cause | None = None,
        held_base: str = "",
    ) -> None:
        """Record a state, optionally with why.

        The note matters where the state does not change — review asking for
        rework leaves a unit open — because without it the entry says only
        that something happened.

        `cause` is why the state changed, kept as a defined value for what
        decides from it; the note is prose for people and nothing reads it.
        `held_by` is who owns a hold and `held_base` the branch a depth hold is
        still on; any other state forgets both.
        """
        record = functools.partial(
            self._record_state,
            unit_id,
            state,
            pr=pr,
            branch=branch,
            note=note,
            held_by=held_by,
            cause=cause,
            held_base=held_base,
        )
        try:
            unit, everything, opened = record()
        except ValueError as error:
            if corrupt_store_message(self.path) not in str(error):
                raise
            # The file can read as torn for a moment where a replace is not atomic
            # (some network filesystems) or while someone edits it by hand; one more
            # look usually finds it whole. The outcome is not worth losing to that.
            time.sleep(1)
            try:
                unit, everything, opened = record()
            except ValueError:
                # Printed, as the tick's journal reads stdout.
                print(f"{unit_id}: stranded — its outcome {state} was not recorded", flush=True)
                raise
        if self.on_state:
            self.on_state(unit, everything, opened)

    @_exclusive
    def _record_state(
        self,
        unit_id: str,
        state: UnitState,
        *,
        pr: int | None,
        branch: str | None,
        note: str,
        held_by: HeldBy,
        cause: Cause | None,
        held_base: str,
    ) -> tuple[StoredUnit, list[StoredUnit], bool]:
        state = UnitState(state)
        stored = self._read()
        unit = stored[unit_id]
        opened = pr is not None and pr != unit.pr
        stored[unit_id] = unit.model_copy(
            update={
                "state": state,
                "pr": pr if pr is not None else unit.pr,
                "branch": branch if branch is not None else unit.branch,
                "held_by": held_by if state == HELD else HeldBy.NONE,
                "held_base": held_base if state == HELD else "",
                # The step belongs to the failure or parking it describes (recorded just
                # before it); any other state forgets it.
                "step": unit.step if state == FAILED or cause in PARKED_CAUSES else "",
                # Parked again, or the count of parkings in a row starts over.
                "parked_attempts": unit.parked_attempts + 1
                if cause in PARKED_CAUSES
                else 0
                if state in (IN_REVIEW, FAILED)
                else unit.parked_attempts,
                "service_attempts": 0 if state in (IN_REVIEW, FAILED) else unit.service_attempts,
                "history": (
                    *unit.history,
                    {
                        "state": state,
                        "at": _now(),
                        **({"note": note} if note else {}),
                        **({"cause": cause.value} if cause else {}),
                    },
                ),
            }
        )
        self._write(stored)
        return stored[unit_id], list(stored.values()), opened

    def count_service_attempt(self, unit_id: str) -> int:
        """Count one more parking in a row on the model service's status; the new count."""
        return self._counted(unit_id, add=True)

    def reset_service_attempts(self, unit_id: str) -> None:
        """A step completed: the row of parkings on the status starts over."""
        self._counted(unit_id, add=False)

    @_exclusive
    def _counted(self, unit_id: str, *, add: bool) -> int:
        stored = self._read()
        unit = stored[unit_id]
        count = unit.service_attempts + 1 if add else 0
        if count != unit.service_attempts:
            stored[unit_id] = unit.model_copy(update={"service_attempts": count})
            self._write(stored)
        return count

    def record_step(self, unit_id: str, step: str) -> None:
        """The step the unit is in when it fails, kept with the failure."""
        self._update(unit_id, step=step)

    @_exclusive
    def _update(self, unit_id: str, **fields: object) -> None:
        stored = self._read()
        stored[unit_id] = stored[unit_id].model_copy(update=fields)
        self._write(stored)

    def set_priority(self, unit_id: str, priority: int) -> None:
        """Set the priority of a unit that has not started; a started one keeps its own."""
        if self.get(unit_id).unstarted:
            self._update(unit_id, priority=priority)

    def set_calibration(self, unit_id: str, flag: str, calibrated_lines: int | None) -> None:
        """The kind's flag and the calibrated figure of a unit that has not started; a
        started unit keeps the figure it was planned with."""
        if self.get(unit_id).unstarted:
            self._update(unit_id, flag=flag, calibrated_lines=calibrated_lines)

    def set_actual_lines(self, unit_id: str, lines: int) -> None:
        """The changed lines of the unit's pull request as the host counts them;
        overwritten at each push. A unit the store does not hold is ignored."""
        try:
            self._update(unit_id, actual_lines=lines)
        except KeyError:
            pass

    def set_feedback(
        self,
        unit_id: str,
        feedback: str,
        *,
        from_person: bool = False,
        source: FeedbackSource = FeedbackSource.NONE,
    ) -> None:
        """What review asked for, or `""` once a run has acted on it.

        `from_person` is True only for words a person left on the pull request;
        every feedback the pipeline writes itself leaves it False, and so does
        clearing it.
        """
        feedback = redact_text(feedback, where="feedback")
        self._update(
            unit_id,
            feedback=feedback,
            feedback_from_person=from_person and bool(feedback),
            feedback_source=source if feedback else FeedbackSource.NONE,
        )

    def set_guidance(self, unit_id: str, guidance: str) -> None:
        """A person's note for the next prompt, or `""` once a run has acted on it."""
        self._update(unit_id, guidance=guidance)

    @_exclusive
    def mark_ready(self, unit_id: str) -> None:
        """Stamp `ready_at` with the clock's now, unless it is already set."""
        self._stamp_once(unit_id, "ready_at")

    @_exclusive
    def mark_human_activity(self, unit_id: str) -> None:
        """Stamp `first_human_activity_at` with the clock's now, unless it is already set."""
        self._stamp_once(unit_id, "first_human_activity_at")

    def _stamp_once(self, unit_id: str, field: str) -> None:
        stored = self._read()
        if getattr(stored[unit_id], field) is None:
            stored[unit_id] = stored[unit_id].model_copy(update={field: spans.clock.now()})
            self._write(stored)

    def set_run_log(self, unit_id: str, name: str) -> None:
        """Name the unit's most recent run log. Not a state change."""
        self._update(unit_id, run_log=name)

    def set_trace(self, unit_id: str, trace: str) -> None:
        """Name where the unit's most recent run is in the traces. Not a state change."""
        self._update(unit_id, trace=trace)

    def set_dependencies(self, unit_id: str, depends_on: Sequence[str]) -> None:
        self._update(unit_id, depends_on=tuple(depends_on))

    def set_gated_requeue(self, unit_id: str, requeue: RequeueReason | None) -> None:
        self._update(unit_id, gated_requeue=requeue)

    def set_parked(
        self, unit_id: str, splits: Sequence[str] = (), sha: str = "", snapshot: str = ""
    ) -> None:
        self._update(unit_id, parked_splits=list(splits), parked_sha=sha, parked_snapshot=snapshot)

    def set_needs(self, unit_id: str, needs: Sequence[str]) -> None:
        self._update(unit_id, needs=tuple(needs))

    def set_close_pending(self, unit_id: str, pending: ClosePending | None) -> None:
        """The close a satisfied unit still owes its pull request, or None once done."""
        self._update(unit_id, close_pending=pending)

    def set_predecessor_note(self, unit_id: str, note: str) -> None:
        self._update(unit_id, predecessor_note=note)

    def set_stack_refusal(self, unit_id: str, reason: str) -> None:
        """Why the host would not stack this unit's PR, or `""` once it did.
        Not a state change: the refusal changes nothing about the unit."""
        self._update(unit_id, stack_refusal=reason)

    def record_approval(
        self, unit_id: str, sha: str, description: Description | None = None
    ) -> None:
        """The commit review approved — the only one the runner may push — and,
        when the reviewer described the branch, that description in place of any earlier."""
        if description is None:
            self._update(unit_id, approved=sha)
        else:
            self._update(unit_id, approved=sha, description=description)

    def record_check_rerun(self, unit_id: str, head: str, count: int) -> None:
        """That the cancelled checks of commit `head` have been re-run `count` times."""
        self._update(unit_id, check_rerun_head=head, check_reruns=count)

    def record_conflict_attempt(
        self, unit_id: str, *, tip: str, head: str, attempts: int, at: datetime
    ) -> None:
        """That a conflict attempt began at base tip `tip` with the unit pushed at `head`,
        the `attempts`-th at that tip."""
        self._update(
            unit_id,
            conflict_tip=tip,
            conflict_head=head,
            conflict_attempts=attempts,
            conflict_at=at,
        )

    def clear_conflict_attempts(self, unit_id: str) -> None:
        """That the unit's conflict attempts are none: a new conflict starts from zero."""
        self._update(
            unit_id, conflict_tip="", conflict_head="", conflict_attempts=0, conflict_at=None
        )

    def record_push(self, unit_id: str, sha: str) -> None:
        """Remember what we published, so the next push can lease against it.

        Separate from `set_state` because a push is not a state change: a unit
        is pushed several times — once per restack — while staying `open`.
        """
        self._update(unit_id, pushed=sha, pushed_at=spans.clock.now())


def _record(unit: StoredUnit) -> dict:
    """The unit as written. The default priority is left out, so a store with no
    unit off it is the one a release before priorities wrote and reads."""
    record = unit.model_dump(mode="json")
    if unit.priority == Priority.NORMAL:
        del record["priority"]
    if unit.description is None:
        del record["description"]
    for name in ("ready_at", "first_human_activity_at", "review_tier"):
        if record[name] is None:
            del record[name]
    return record


def _with_state(unit: StoredUnit, state: UnitState) -> StoredUnit:
    """Change a unit's state and record that it happened.

    `upsert` used to write `unplanned` straight onto the model, so the one
    transition that stops a unit building was the one transition that left no
    trace — every other goes through `set_state`, which records it.
    """
    state = UnitState(state)
    return unit.model_copy(
        update={"state": state, "history": (*unit.history, {"state": state, "at": _now()})}
    )


def _now() -> str:
    # The clock `backoff_remaining` is read against, so a parking is stamped and measured alike.
    return spans.clock.now().isoformat()


# The causes of a unit parked because something outside it is down: it resumes at its
# step once `PARK_BACKOFF` has elapsed.
PARKED_CAUSES = (Cause.HOST_UNAVAILABLE, Cause.NETWORK_UNAVAILABLE, Cause.SERVICE_UNAVAILABLE)

# What each parked cause waits for, as the status, the log and the graph say it.
_WAITING_FOR = {
    Cause.HOST_UNAVAILABLE: "waiting for the code host",
    Cause.NETWORK_UNAVAILABLE: "waiting for the network",
    Cause.SERVICE_UNAVAILABLE: "waiting for the model service",
}


def waiting_for(unit: StoredUnit) -> str:
    """What a unit parked for an outage waits for, or "" for any other unit."""
    return _WAITING_FOR.get(unit.cause, "") if unit.cause else ""


# How long a parked unit waits, by consecutive parking.
PARK_BACKOFF = (
    timedelta(minutes=1),
    timedelta(minutes=2),
    timedelta(minutes=5),
    timedelta(minutes=10),
    timedelta(minutes=30),
)


def backoff_ends(unit: StoredUnit) -> datetime | None:
    """When a unit parked for the host, the network or the model service may run again, or
    None when it is not parked."""
    if unit.state != PLANNED or unit.cause not in PARKED_CAUSES:
        return None
    try:
        parked = datetime.fromisoformat(str(unit.history[-1].get("at", "")))
    except ValueError:
        return None
    return parked + PARK_BACKOFF[min(max(unit.parked_attempts, 1), len(PARK_BACKOFF)) - 1]


def backoff_remaining(unit: StoredUnit, now: datetime) -> timedelta | None:
    """How long until a unit parked for the host, the network or the model service being
    unavailable may run again, or None when it is not parked, or the wait is over."""
    if (ends := backoff_ends(unit)) is None:
        return None
    left = ends - now
    return left if left > timedelta(0) else None


def awaits_release(unit: StoredUnit) -> bool:
    """Whether a planned unit is stopped until something releases it: a gated requeue to be
    delivered, or tier 2 tests parked for a held split. A tick never starts one."""
    return unit.cause is Cause.SPLIT_HELD or (
        unit.cause is Cause.GATED and unit.gated_requeue is not None
    )
