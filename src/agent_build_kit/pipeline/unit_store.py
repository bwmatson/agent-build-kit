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
import os
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from agent_build_kit.pipeline.file_lock import file_lock
from agent_build_kit.pipeline.units import PLANNED, Join, Member, Unit

# A unit that the latest plan no longer contains. Kept rather than deleted: it
# may already have an open PR, and the runner needs to see that the plan moved.
UNPLANNED = "unplanned"


def corrupt_store_message(path: Path) -> str:
    return f"unit store at {path} could not be read"


class StoredUnit(Unit):
    """A unit plus what has happened to it."""

    branch: str = ""
    pr: int | None = None
    # The SHA this runner last published for `branch`. The next push leases
    # against exactly this, so it has to outlive the process that pushed it.
    pushed: str | None = None
    # What review asked for, waiting to be addressed. Cleared once a run has
    # acted on it, so a unit is never reworked twice for the same comment.
    feedback: str = ""
    # The step a unit stopped before, when it stopped between steps; empty
    # otherwise. The runner resumes there rather than guessing from the branch.
    resume_from: str = ""
    # The commit the review loop last approved. Nothing else may be pushed:
    # see the gate before `push` in `StackRunner.run`.
    approved: str = ""
    # The approved verdict's deferrable points, waiting for the push that makes
    # them true. Kept here, not in the run: a unit that stops between approval
    # and push resumes at VERIFY with no review to repeat them.
    deferred: tuple[str, ...] = ()
    # A PR rework's replies, waiting for the push that makes them true. Kept
    # here, not in the run: a rework that writes its replies, then pauses for
    # usage before its push, would otherwise lose them with the process.
    pending_replies: tuple[str, ...] = ()
    # Set when the unit was moved onto a predecessor that changed under it,
    # for the reviewer: which files needed resolving, or how its tests were
    # carried over. Cleared once the unit is back in review.
    predecessor_note: str = ""
    # The review loop so far: each round's ask and the builder's response, for
    # later rounds to check against instead of starting over. Kept here so a
    # loop that pauses or is killed resumes with it. Cleared once in review.
    review_rounds: tuple[dict, ...] = ()
    # The file name of this unit's most recent run log (see `run_log`); empty
    # until it has run.
    run_log: str = ""
    # Why the host last refused to register this unit's pull request in a
    # stack; empty when it did, or was never asked. Advisory: nothing reads it
    # to decide anything.
    stack_refusal: str = ""
    history: tuple[dict, ...] = ()

    @property
    def unstarted(self) -> bool:
        """Planned, with no branch, commit, pull request or step to resume at:
        nothing exists that removing or extending this unit could disturb."""
        return self.state == PLANNED and not (
            self.branch or self.pr is not None or self.pushed or self.resume_from or self.approved
        )

    @property
    def note(self) -> str:
        """Why the unit is in its present state, as its latest history entry says."""
        return str(self.history[-1].get("note", "")) if self.history else ""


StateChanged = Callable[[StoredUnit, list[StoredUnit], bool], None]


def _exclusive(method):
    """One change to the store at a time.

    Every change reads the whole file, edits it and writes it back, so two
    units building in parallel could each read, and the second write would
    drop the first's change — a unit's state, or the SHA a push leases on.
    """

    @functools.wraps(method)
    def locked(self: UnitStore, *args, **kwargs):
        with file_lock(self.path.with_name(f"{self.path.name}.lock")):
            return method(self, *args, **kwargs)

    return locked


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
        payload = {"units": [unit.model_dump(mode="json") for unit in stored.values()]}
        # Indented and one key per line: this file is committed, so it turns up
        # in diffs and reviews, where dense JSON is unreadable.
        # Written aside and renamed into place: reads are not locked, and a
        # reader catching a half-written file would take it for corruption.
        partial = self.path.with_name(f"{self.path.name}.tmp")
        partial.write_text(json.dumps(payload, indent=2) + "\n")
        os.replace(partial, self.path)
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
                # Work in progress, not shape: a re-plan must not drop what
                # review asked for, or where a paused unit should pick up.
                feedback=existing.feedback if existing else "",
                resume_from=existing.resume_from if existing else "",
                approved=existing.approved if existing else "",
                deferred=existing.deferred if existing else (),
                pending_replies=existing.pending_replies if existing else (),
                predecessor_note=existing.predecessor_note if existing else "",
                review_rounds=existing.review_rounds if existing else (),
                run_log=existing.run_log if existing else "",
                stack_refusal=existing.stack_refusal if existing else "",
                history=existing.history if existing else ({"state": PLANNED, "at": _now()},),
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
        state: str,
        *,
        pr: int | None = None,
        branch: str | None = None,
        note: str = "",
        resume_from: str | None = None,
    ) -> None:
        """Record a state, optionally with why.

        The note matters where the state does not change — review asking for
        rework leaves a unit open — because without it the entry says only
        that something happened.
        """
        unit, everything, opened = self._record_state(
            unit_id, state, pr=pr, branch=branch, note=note, resume_from=resume_from
        )
        if self.on_state:
            self.on_state(unit, everything, opened)

    @_exclusive
    def _record_state(
        self,
        unit_id: str,
        state: str,
        *,
        pr: int | None,
        branch: str | None,
        note: str,
        resume_from: str | None,
    ) -> tuple[StoredUnit, list[StoredUnit], bool]:
        stored = self._read()
        unit = stored[unit_id]
        opened = pr is not None and pr != unit.pr
        stored[unit_id] = unit.model_copy(
            update={
                "state": state,
                "pr": pr if pr is not None else unit.pr,
                "branch": branch if branch is not None else unit.branch,
                "resume_from": resume_from if resume_from is not None else unit.resume_from,
                "history": (
                    *unit.history,
                    {"state": state, "at": _now(), **({"note": note} if note else {})},
                ),
            }
        )
        self._write(stored)
        return stored[unit_id], list(stored.values()), opened

    @_exclusive
    def _update(self, unit_id: str, **fields: object) -> None:
        stored = self._read()
        stored[unit_id] = stored[unit_id].model_copy(update=fields)
        self._write(stored)

    def set_feedback(self, unit_id: str, feedback: str) -> None:
        """What review asked for, or `""` once a run has acted on it."""
        self._update(unit_id, feedback=feedback)

    def record_step(self, unit_id: str, step: str) -> None:
        """The step a running unit is starting, so a run killed inside it
        resumes there. Not a state change, so no history entry."""
        self._update(unit_id, resume_from=step)

    def set_run_log(self, unit_id: str, name: str) -> None:
        """Name the unit's most recent run log. Not a state change."""
        self._update(unit_id, run_log=name)

    def set_pending_replies(self, unit_id: str, replies: Sequence[str]) -> None:
        self._update(unit_id, pending_replies=tuple(replies))

    def set_dependencies(self, unit_id: str, depends_on: Sequence[str]) -> None:
        self._update(unit_id, depends_on=tuple(depends_on))

    def set_merge_before(self, unit_id: str, merge_before: Sequence[str]) -> None:
        self._update(unit_id, merge_before=tuple(merge_before))

    def set_review_rounds(self, unit_id: str, rounds: Sequence[dict]) -> None:
        self._update(unit_id, review_rounds=tuple(rounds))

    def set_predecessor_note(self, unit_id: str, note: str) -> None:
        self._update(unit_id, predecessor_note=note)

    def set_stack_refusal(self, unit_id: str, reason: str) -> None:
        """Why the host would not stack this unit's PR, or `""` once it did.
        Not a state change: the refusal changes nothing about the unit."""
        self._update(unit_id, stack_refusal=reason)

    def record_approval(
        self, unit_id: str, sha: str, deferred: Sequence[str] | None = None
    ) -> None:
        """The commit review approved — the only one the runner may push.

        `deferred` replaces the recorded follow-ups, so a later approval with
        none clears an earlier one's; left as `None` (a restack re-approving
        a moved commit) it keeps them.
        """
        if deferred is None:
            self._update(unit_id, approved=sha)
        else:
            self._update(unit_id, approved=sha, deferred=tuple(deferred))

    def set_deferred(self, unit_id: str, deferred: Sequence[str]) -> None:
        self._update(unit_id, deferred=tuple(deferred))

    def record_push(self, unit_id: str, sha: str) -> None:
        """Remember what we published, so the next push can lease against it.

        Separate from `set_state` because a push is not a state change: a unit
        is pushed several times — once per restack — while staying `open`.
        """
        self._update(unit_id, pushed=sha)


def _with_state(unit: StoredUnit, state: str) -> StoredUnit:
    """Change a unit's state and record that it happened.

    `upsert` used to write `unplanned` straight onto the model, so the one
    transition that stops a unit building was the one transition that left no
    trace — every other goes through `set_state`, which records it.
    """
    return unit.model_copy(
        update={"state": state, "history": (*unit.history, {"state": state, "at": _now()})}
    )


def _now() -> str:
    return datetime.now(UTC).isoformat()
