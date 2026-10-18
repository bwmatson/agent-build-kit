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
from collections.abc import Callable, Collection, Mapping, Sequence
from contextlib import AbstractContextManager
from datetime import datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any

from pydantic import Field, ValidationError, field_validator, model_validator

from agent_build_kit.budget import cut_head
from agent_build_kit.compat_names import Place, new_spelling
from agent_build_kit.model import Frozen, TestTier, widest_kind
from agent_build_kit.pipeline import spans
from agent_build_kit.pipeline.file_lock import atomic_write_text, file_lock
from agent_build_kit.pipeline.units import (
    FAILED,
    HELD,
    IN_REVIEW,
    PLANNED,
    RUNNING,
    SPLIT_HELD_CAUSE,
    Join,
    Member,
    Priority,
    Unit,
    UnitState,
    direct_dependencies,
    history_stamp,
    repointed,
)
from agent_build_kit.pipeline.work_graph import FLAGS
from agent_build_kit.redaction import redact_text

# A unit that the latest plan no longer contains. Kept rather than deleted: it
# may already have an open PR, and the runner needs to see that the plan moved.
UNPLANNED = UnitState.UNPLANNED

# What `abk requeue` writes as `by`: a person's requeue ends a unit's run of bounces.
REQUEUE_BY = "abk requeue"

# Writing a unit into one of these ends its run of bounces: it is in review, failed or finished.
_ENDS_BOUNCES = (
    UnitState.IN_REVIEW,
    UnitState.FAILED,
    UnitState.MERGED,
    UnitState.CLOSED,
    UnitState.SATISFIED,
    UnitState.UNPLANNED,
    UnitState.RETIRED,
)


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
    causes were kept has none. A cause is standing (`STANDING_CAUSES`: it lasts until
    a state change passes another) or an event (`EVENT_CAUSES`: a transition that is over)."""

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
    RESTACK_HANDED_BACK = "restack_handed_back"
    DIRTY_WORKTREE = "dirty_worktree"
    ATTACHED = "attached"
    ADOPTED = "adopted"
    MERGED = "merged"
    AUTO_LANDED = "auto_landed"
    CLOSED = "closed"
    RETIRED = "retired"
    FAILED = "failed"
    HOST_UNAVAILABLE = "host_unavailable"
    NETWORK_UNAVAILABLE = "network_unavailable"
    SERVICE_UNAVAILABLE = "service_unavailable"
    ENVIRONMENT = "environment"
    SPLIT_HELD = SPLIT_HELD_CAUSE


class Keep:
    """The sentinel `KEEP`: a state change the store makes on its own account passes it as
    the cause to carry the unit's standing cause forward."""


KEEP = Keep()

# The two kinds of cause, which together are exactly the members of `Cause`. A standing cause
# names a situation that lasts until a state change passes another cause; an event cause names
# a transition that has happened and is over, and ends a standing one when it is recorded.
EVENT_CAUSES: frozenset[Cause] = frozenset(
    {
        Cause.REQUEUED,
        Cause.RELEASED,
        Cause.ADOPTED,
        Cause.MERGED,
        Cause.AUTO_LANDED,
        Cause.CLOSED,
        Cause.RETIRED,
        Cause.FAILED,
    }
)
STANDING_CAUSES: frozenset[Cause] = frozenset(Cause) - EVENT_CAUSES


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
    UNIT_TEST = "unit-test"
    E2E = "e2e-test"

    @classmethod
    def _missing_(cls, value: object) -> FeedbackSource | None:
        """A source stored under the old spelling is the kind it meant."""
        if isinstance(value, str) and new_spelling(Place.VALUE, value) != value:
            return cls(new_spelling(Place.VALUE, value))
        return None


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


class Collision(Frozen):
    """A group a plan gives to `claimant` while `owner`, a started unit, carries it."""

    change: str
    group: int
    owner: str
    owner_state: UnitState
    claimant: str


class GroupOwned(Exception):
    """A plan gives a group to a unit while a started unit that has not finished carries it.
    The message names both units and the group; nothing is written."""

    def __init__(self, collisions: Sequence[Collision]) -> None:
        self.collisions = tuple(collisions)
        super().__init__(
            "; ".join(
                f"{c.change} group {c.group} is carried by {c.owner} ({c.owner_state.value}), "
                f"so {c.claimant} cannot take it"
                for c in self.collisions
            )
        )


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
    # Times in a row the unit went from `running` back to `planned` or `held` after a short
    # run with the same cause, that cause, and when the last was counted.
    bounces: int = 0
    bounce_cause: Cause | None = None
    bounce_at: datetime | None = None
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
    # Whether the restack lane is making this unit's whole run (see `moved_base_units`).
    moved_base_run: bool = False
    # Whether that run began and no attempt at its base's tip is recorded for it, because it
    # stopped before its first agent call: its resume is then the attempt.
    moved_base_uncounted: bool = False
    # Why the unit is held (see `HeldBy`).
    held_by: HeldBy = HeldBy.NONE
    # The branch a unit held for depth is still on.
    held_base: str = ""
    # How a requeue that found a dependency it waits on unmet is delivered once
    # it is met (see `Cause.GATED`); None when no requeue is waiting.
    gated_requeue: RequeueReason | None = None
    # The units a failed unit was recorded waiting on, until the requeue when that wait ended.
    waited_on: tuple[str, ...] = ()
    # What a unit left failed when its wait ended says to a person, until a requeue.
    wait_ended: str = ""
    # What a unit held for `Cause.SPLIT_HELD` waits on: the splits its e2e-test run
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
        return self.state == PLANNED and not self.has_work

    @property
    def owns_groups(self) -> bool:
        """Whether the groups this unit carries are its to build: planned, running, in review,
        failed or held, or unplanned with a branch, pull request, pushed commit or approval."""
        if self.state == UNPLANNED:
            return self.has_work
        return self.state in (PLANNED, RUNNING, IN_REVIEW, FAILED, HELD)

    @property
    def has_work(self) -> bool:
        """A branch, pull request, pushed commit or approval exists for the unit."""
        return bool(self.branch or self.pr is not None or self.pushed or self.approved)

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
    def sent_back_for_conflict(self) -> bool:
        """Whether the unit was sent back for its pull request's conflict: its run is the
        conflict's rework, which starts at the move."""
        return self.cause is Cause.REWORK and self.feedback_source is FeedbackSource.CONFLICT

    def has_own_rework_input(self, head: str) -> bool:
        """Whether the unit has saved feedback that is not the conflict's and that review has
        not answered by approving `head`: rework of its own, which makes its run a build."""
        return (
            bool(self.feedback)
            and self.feedback_source is not FeedbackSource.CONFLICT
            and not (bool(self.approved) and self.approved == head)
        )

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

    @property
    def cause_since(self) -> datetime | None:
        """When the entry that set the current cause was written, or `None` without one.

        Entries a carry wrote are skipped: they repeat a cause, they do not set it. A second
        parking is not a carry, so it counts."""
        if self.cause is None:
            return None
        for entry in reversed(self.history):
            if not entry.get("carried"):
                try:
                    return datetime.fromisoformat(str(entry.get("at", "")))
                except ValueError:
                    return None
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


def _reduced(stored: dict[str, StoredUnit], unit_id: str) -> StoredUnit:
    unit = stored[unit_id]
    return unit.model_copy(update={"depends_on": direct_dependencies(unit, list(stored.values()))})


class UnitStore:
    """The planning repo's record of every unit, across all repos."""

    def __init__(
        self,
        path: Path,
        *,
        on_write: Callable[[list[StoredUnit]], None] | None = None,
        on_state: StateChanged | None = None,
        bounce_span_seconds: int = 120,
    ) -> None:
        """`bounce_span_seconds` is the longest run that still counts as a bounce when a unit
        is put back from `running` (`_bounces`).

        `on_write` sees every unit after each change — how the diagram stays
        current without every call site that changes a state remembering it.

        `on_state` hears each `set_state` once the change is written and the
        store unlocked, with the unit, every unit, and whether this call is
        what first recorded its pull request. How a pull request's labels
        follow its unit, again without each call site remembering."""
        self.path = path
        self.on_write = on_write
        self.on_state = on_state
        self.bounce_span_seconds = bounce_span_seconds

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
        before = dict(stored)
        planned_ids = {unit.id for unit in units}

        for unit in units:
            existing = stored.get(unit.id)
            if existing and existing.state == UnitState.RETIRED:
                # Ended by a person: no plan revives or reshapes it.
                continue
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
                bounces=existing.bounces if existing else 0,
                bounce_cause=existing.bounce_cause if existing else None,
                bounce_at=existing.bounce_at if existing else None,
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
                # What a parked unit waits on survives a replan and a demotion.
                parked_splits=existing.parked_splits if existing else [],
                parked_sha=existing.parked_sha if existing else "",
                parked_snapshot=existing.parked_snapshot if existing else "",
                parked_attempts=existing.parked_attempts if existing else 0,
                # Runtime state, not shape: a replan must not drop what a run left.
                service_attempts=existing.service_attempts if existing else 0,
                gated_requeue=existing.gated_requeue if existing else None,
                waited_on=existing.waited_on if existing else (),
                wait_ended=existing.wait_ended if existing else "",
                close_pending=existing.close_pending if existing else None,
                step=existing.step if existing else "",
                guidance=existing.guidance if existing else "",
                ready_at=existing.ready_at if existing else None,
                first_human_activity_at=existing.first_human_activity_at if existing else None,
                moved_base_run=existing.moved_base_run if existing else False,
                moved_base_uncounted=existing.moved_base_uncounted if existing else False,
                history=existing.history if existing else ({"state": PLANNED, "at": _now()},),
            )
            if existing and not existing.unstarted:
                # A unit keeps the priority, project, split and review tier it started with.
                fresh = fresh.model_copy(
                    update={
                        "priority": existing.priority,
                        "promoted_from": existing.promoted_from,
                        "project": existing.project,
                        "split": existing.split,
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
                        # Nor is the kind a joined group widened it to.
                        "tier": widest_kind([fresh.tier, existing.tier]),
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
                    fresh = _with_state(fresh, PLANNED, KEEP)
                else:
                    fresh = fresh.model_copy(update={"state": existing.state})
            stored[unit.id] = fresh

        for unit in units:
            stored[unit.id] = _reduced(stored, unit.id)

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
                if not unit.unstarted:
                    continue
                if unit.change == change and unit_id not in planned_ids:
                    stored[unit_id] = _with_state(unit, UNPLANNED, KEEP)

        if collisions := _new_collisions(before, stored):
            raise GroupOwned(collisions)
        self._write(stored)

    def retire(self, unit_id: str, reason: str = "") -> None:
        """End a unit: state `retired`, cause `retired` and one history entry with the reason
        (`retired` when none is given) and `by: abk retire`, in one write. The branch and the
        pull request stay as they are. The write is made under the store's lock by
        `_record_state`, as `set_state` does; the lock is not re-entrant."""
        unit, everything, opened = self._record_state(
            unit_id,
            UnitState.RETIRED,
            pr=None,
            branch=None,
            note=reason or "retired",
            held_by=HeldBy.NONE,
            cause=Cause.RETIRED,
            held_base="",
            by="abk retire",
        )
        if self.on_state:
            self.on_state(unit, everything, opened)

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
            stored[unit_id] = _with_state(stored[unit_id], UNPLANNED, KEEP)
        if dropped:
            self._write(stored)
        return dropped

    @_exclusive
    def join(self, join: Join, *, group_kinds: Sequence[TestTier]) -> tuple[int, int] | None:
        """Apply a planned join, or return `None` and change nothing.

        Both units are read again here, because either may have started since
        the plan was made. On success the units' estimates before and after
        are returned, `onto` carries the work, a unit joined in is removed and
        whatever depended on it depends on `onto`. `onto` takes the widest kind of its own, the
        unit joined in and `group_kinds`, the kinds of the groups a change's join brings.
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
        grown = onto.taking(
            members,
            estimated_lines=added,
            kinds=[*group_kinds, *([taken.tier] if taken is not None else [])],
        )
        stored[onto.id] = grown.model_copy(
            update={
                "history": (*onto.history, _entry(onto, onto.state, KEEP, "joined")),
            }
        )
        if taken is not None:
            del stored[taken.id]
            stored.update(repointed(stored, taken.id, onto.id))
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
        cause: Cause | None | Keep = None,
        held_base: str = "",
        by: str = "",
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
            by=by,
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
        cause: Cause | None | Keep,
        held_base: str,
        by: str = "",
    ) -> tuple[StoredUnit, list[StoredUnit], bool]:
        state = UnitState(state)
        stored = self._read()
        unit = stored[unit_id]
        # Resolved first: a carried parking keeps its step, and is not another parking.
        resolved = _resolve(unit, cause)
        opened = pr is not None and pr != unit.pr
        stored[unit_id] = unit.model_copy(
            update={
                "state": state,
                "pr": pr if pr is not None else unit.pr,
                "branch": branch if branch is not None else unit.branch,
                "held_by": held_by if state == HELD else HeldBy.NONE,
                # The lane's run of the unit lasts while it is running.
                "moved_base_run": unit.moved_base_run and state == RUNNING,
                "moved_base_uncounted": unit.moved_base_uncounted and state == RUNNING,
                "held_base": held_base if state == HELD else "",
                # The step belongs to the failure or parking it describes (recorded just
                # before it); any other state forgets it.
                "step": unit.step if state == FAILED or resolved in PARKED_CAUSES else "",
                # Parked again, or the count of parkings in a row starts over.
                "parked_attempts": unit.parked_attempts + 1
                if not isinstance(cause, Keep) and cause in PARKED_CAUSES
                else 0
                if state in (IN_REVIEW, FAILED)
                else unit.parked_attempts,
                "service_attempts": 0 if state in (IN_REVIEW, FAILED) else unit.service_attempts,
                # A gate is closed in the write that changes the cause.
                "gated_requeue": unit.gated_requeue if resolved is Cause.GATED else None,
                **self._bounces(unit, state, resolved, by),
                "history": (*unit.history, _entry(unit, state, cause, note, by)),
            }
        )
        self._write(stored)
        return stored[unit_id], list(stored.values()), opened

    def _bounces(
        self, unit: StoredUnit, state: UnitState, cause: Cause | None, by: str
    ) -> dict[str, object]:
        """The bounce fields after `unit` is written into `state`: the count goes up for a
        short run put back to `planned` or `held` with the cause of the last bounce,
        restarts for another cause, and is zero after a long run, no cause, a person's
        requeue, review, failure or a finished state. Any other write leaves it."""
        zero: dict[str, object] = {"bounces": 0, "bounce_cause": None, "bounce_at": None}
        if by == REQUEUE_BY or state in _ENDS_BOUNCES:
            return zero
        if unit.state != RUNNING or state not in (PLANNED, HELD):
            return {}
        now = spans.clock.now()
        started = next(
            (
                stamp
                for entry in reversed(unit.history)
                if entry.get("state") == RUNNING and (stamp := history_stamp(entry))
            ),
            None,
        )
        try:
            ran = (now - started).total_seconds() if started else None
        except TypeError:
            ran = None
        if not isinstance(cause, Cause) or ran is None or ran >= self.bounce_span_seconds:
            return zero
        count = unit.bounces + 1 if unit.bounce_cause is cause else 1
        return {"bounces": count, "bounce_cause": cause, "bounce_at": now}

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
            self._update(unit_id, priority=priority, promoted_from="")

    def set_promotion(self, unit_id: str, priority: int, promoted_from: str) -> None:
        """Give an unstarted unit the priority a waiter needs of it, and name the waiter."""
        if self.get(unit_id).unstarted:
            self._update(unit_id, priority=priority, promoted_from=promoted_from)

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

    def set_moved_base_run(self, unit_id: str, flag: bool) -> None:
        """Whether the restack lane is making the unit's whole run."""
        self._update(unit_id, moved_base_run=flag)

    def set_moved_base_uncounted(self, unit_id: str, flag: bool) -> None:
        """Whether the lane's run of the unit began with no attempt recorded for it."""
        self._update(unit_id, moved_base_uncounted=flag)

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

    @_exclusive
    def set_dependencies(self, unit_id: str, depends_on: Sequence[str]) -> None:
        """Store the direct dependencies of the list given."""
        stored = self._read()
        stored[unit_id] = stored[unit_id].model_copy(update={"depends_on": tuple(depends_on)})
        stored[unit_id] = _reduced(stored, unit_id)
        self._write(stored)

    def set_waited_on(self, unit_id: str, waited_on: Sequence[str]) -> None:
        self._update(unit_id, waited_on=tuple(waited_on))

    def set_wait_ended(self, unit_id: str, wait_ended: str) -> None:
        self._update(unit_id, wait_ended=wait_ended)

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


def _carries(unit: StoredUnit | None) -> set[tuple[str, int]]:
    """The (change, group) pairs the unit builds, its own and joined."""
    if unit is None:
        return set()
    return {(member.change, number) for member in unit.members() for number in member.groups}


def _new_collisions(
    before: Mapping[str, StoredUnit], after: Mapping[str, StoredUnit]
) -> list[Collision]:
    """The collisions `after` has that `before` did not, in a stable order: a new claimant, or
    an owner that began to carry the group. Who owned what is decided on both sides, so a
    record that merely listed the group is not an existing collision."""
    known = _collisions(before)
    return sorted(
        (c for c in _collisions(after) if c not in known),
        key=lambda c: (c.change, c.group, c.owner, c.claimant),
    )


def _collisions(units: Mapping[str, StoredUnit]) -> set[Collision]:
    """Every group an owner that has started carries while another owner carries it too."""
    owners: dict[tuple[str, int], list[StoredUnit]] = {}
    for unit in units.values():
        if unit.owns_groups:
            for pair in _carries(unit):
                owners.setdefault(pair, []).append(unit)
    return {
        Collision(
            change=change,
            group=group,
            owner=owner.id,
            owner_state=owner.state,
            claimant=claimant.id,
        )
        for (change, group), carriers in owners.items()
        for owner in carriers
        if not owner.unstarted
        for claimant in carriers
        if claimant.id != owner.id
    }


def _record(unit: StoredUnit) -> dict:
    """The unit as written. The default priority is left out, so a store with no
    unit off it is the one a release before priorities wrote and reads."""
    record = unit.model_dump(mode="json")
    if unit.priority == Priority.NORMAL:
        del record["priority"]
    if not unit.promoted_from:
        del record["promoted_from"]
    if unit.description is None:
        del record["description"]
    for name in ("ready_at", "first_human_activity_at", "review_tier"):
        if record[name] is None:
            del record[name]
    return record


def _resolve(unit: StoredUnit, cause: Cause | None | Keep) -> Cause | None:
    """The cause an entry records: `KEEP` is the unit's own cause when it is standing, and
    none when it is an event cause or there is none."""
    if isinstance(cause, Keep):
        return unit.cause if unit.cause in STANDING_CAUSES else None
    return cause


def _entry(
    unit: StoredUnit, state: UnitState, cause: Cause | None | Keep, note: str = "", by: str = ""
) -> dict:
    """The history entry for `unit` changing to `state`. With `KEEP` it repeats the standing
    cause and the previous note (unless one is given) and is marked `carried`, so
    `cause_since` and a reader of the history can tell a carry from the cause being set.
    `by` names the command that did it when a command did, never a person."""
    resolved = _resolve(unit, cause)
    carried = isinstance(cause, Keep) and resolved is not None
    if carried and not note and unit.history:
        note = str(unit.history[-1].get("note", ""))
    return {
        "state": state,
        "at": _now(),
        **({"note": note} if note else {}),
        **({"cause": resolved.value} if resolved else {}),
        **({"carried": True} if carried else {}),
        **({"by": by} if by else {}),
    }


def _with_state(
    unit: StoredUnit, state: UnitState, cause: Cause | None | Keep = None
) -> StoredUnit:
    """Change a unit's state and record that it happened.

    `upsert` used to write `unplanned` straight onto the model, so the one
    transition that stops a unit building was the one transition that left no
    trace — every other goes through `set_state`, which records it.
    """
    state = UnitState(state)
    return unit.model_copy(
        update={"state": state, "history": (*unit.history, _entry(unit, state, cause))}
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
    parked = unit.cause_since
    if parked is None:
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
    """Whether a planned unit is stopped until something releases it: a saved requeue to be
    delivered (whatever the cause a replan or an older record left), or e2e tests parked for a
    held split. A tick never starts one."""
    return unit.cause is Cause.SPLIT_HELD or (
        unit.state == PLANNED and unit.gated_requeue is not None
    )
