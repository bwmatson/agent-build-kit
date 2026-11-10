"""The resolution lane restacks run in: its own workers, apart from the build pool.

A restack is the part of a unit's flow whose only cause is that its base moved.
It takes no build slot, starts when it is seen, and runs in the order it was
seen, at most `project_limits.max_concurrent_resolutions` at once for a project and, when the
unit's account sets the same field, at most that many at once across the account's projects.
The lane holds no turn
of its own: the move takes the repository's turn for the phases that write shared
git state.
"""

from __future__ import annotations

import contextvars
import hashlib
import json
import os
import threading
from collections.abc import Callable, Collection, Hashable, Mapping
from concurrent.futures import Future
from datetime import datetime
from pathlib import Path
from types import TracebackType
from typing import Any

from agent_build_kit.config import active
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline import host, spans
from agent_build_kit.pipeline.events import Claim, hold_for_conflict, read_base_tip
from agent_build_kit.pipeline.file_lock import atomic_write_text
from agent_build_kit.pipeline.lease import Leases, lease_dir
from agent_build_kit.pipeline.shell import git
from agent_build_kit.pipeline.unit_store import (
    Cause,
    FeedbackSource,
    StoredUnit,
    UnitStore,
)
from agent_build_kit.pipeline.units import (
    IN_REVIEW,
    PLANNED,
    RUNNING,
    ProjectKey,
    base_of,
    branch_name,
    local_ref,
    project_key,
    waiting_on,
)
from agent_build_kit.pipeline.wiring import branch_commits, is_ancestor
from agent_build_kit.pipeline.workspaces import BranchBusy, branch_held, holder_alive

# A move, or a run's work, returns what remains to run in the same worker once the unit's
# branch claim is released: the unit's own run, which takes the branch lock itself.
Rest = Callable[[], None]
Move = Callable[[StoredUnit], Rest | None]
Work = Callable[[], Rest | None]
Owed = Callable[[list[StoredUnit]], Collection[str]]
Stamp = Callable[[StoredUnit], object]

# Each project's lane writes its record (`record_path`) in the state directory, for `abk status`
# and the graph page, which are not the process that runs the tick. The glob also reads the
# single record a tick of the previous version left as `restacks.json`.
RECORD_GLOB = "restacks*.json"

OWED_STATES = (PLANNED, RUNNING, IN_REVIEW)
OWED_CAUSES = (Cause.BASE_CHANGED, Cause.RESTACK_DEFERRED)
# The causes of a unit owed a moved-base run: a restack is owed for the first two only.
MOVED_BASE_CAUSES = (*OWED_CAUSES, Cause.RESTACK_CONFLICT)


def in_a_lane_run(unit: StoredUnit) -> bool:
    """Whether the lane is making the unit's whole run, so it is the lane's to resume."""
    return unit.state == RUNNING and unit.moved_base_run


def in_a_comment_run(unit: StoredUnit) -> bool:
    """Whether the lane is making the unit's comment rework, which holds no build worker."""
    return unit.in_a_comment_run


def resolving_phrase(kind: str, base: str) -> str:
    """How the status and `abk explain` say what a unit is resolving."""
    return "resolving a comment" if kind == "comment" else f"resolving base {base}"


def about_the_move(unit: StoredUnit) -> bool:
    """Whether the unit's run is about its base moving, a moved-base cause or a conflict sent
    back, and so an attempt at the base's tip; a comment or a change request is not."""
    return unit.cause in MOVED_BASE_CAUSES or unit.sent_back_for_conflict


class Holds:
    """What keeps a unit from being owed a run, read once for a scan: a lease that names it, or
    a lock on its branch."""

    def __init__(self, inst: Installation) -> None:
        self._leases = Leases(lease_dir(inst.local_dir))
        self._locks = inst.locks_dir

    def held(self, unit: StoredUnit) -> bool:
        return branch_held(_branch_of(unit), root=self._locks)

    def leased(self, unit: StoredUnit) -> bool:
        return self._leases.holder(unit.id) is not None


def _free_to_run(
    unit: StoredUnit,
    graph: list[StoredUnit],
    *,
    held: Callable[[StoredUnit], bool],
    leased: Callable[[StoredUnit], bool],
) -> bool:
    """Whether nothing keeps `unit` from a run: it waits on no unmerged unit, no lease names it
    and no run holds its branch."""
    return not waiting_on(unit, graph) and not leased(unit) and not held(unit)


def owed_a_restack(
    unit: StoredUnit,
    graph: list[StoredUnit],
    *,
    holds_base: Callable[[StoredUnit], bool],
    held: Callable[[StoredUnit], bool],
    leased: Callable[[StoredUnit], bool],
) -> bool:
    """Whether `unit` is owed a restack: its cause says its base moved, its branch does
    not hold the base, no run holds the branch, no lease names it, and nothing it
    depends on is unmerged."""
    # The cause is standing, so a replan carries it and the answer is the same after one.
    return (
        unit.state in OWED_STATES
        and unit.cause in OWED_CAUSES
        and _free_to_run(unit, graph, held=held, leased=leased)
        and not holds_base(unit)
    )


def _branch_of(unit: StoredUnit) -> str:
    return unit.branch or branch_name(unit)


def _branch_head(checkouts: Mapping[str, Path], unit: StoredUnit) -> str:
    """The commit the unit's branch is at, empty when the checkout or the branch is missing."""
    repo = checkouts[unit.repo]
    if not repo.is_dir():
        return ""
    return git(
        repo, "rev-parse", "--verify", "--quiet", _branch_of(unit), check=False
    ).stdout.strip()


def owed_a_moved_base_run(
    unit: StoredUnit,
    graph: list[StoredUnit],
    *,
    has_commits: Callable[[StoredUnit], bool],
    head: Callable[[StoredUnit], str],
    held: Callable[[StoredUnit], bool],
    leased: Callable[[StoredUnit], bool],
) -> bool:
    """Whether `unit` is owed a moved-base run: it has commits, nothing holds it or it waits
    on, its cause is a moved base or a conflict sent back, and it has no rework input of
    its own (feedback that review has approved over is answered, the conflict's is not input)."""
    # The cause is standing, so a replan carries it and this reads the same after one.
    return (
        unit.state in (PLANNED, IN_REVIEW)
        and about_the_move(unit)
        and _free_to_run(unit, graph, held=held, leased=leased)
        and has_commits(unit)
        and not unit.has_own_rework_input(head(unit))
    )


def clear_answered_feedback(store: UnitStore, unit: StoredUnit, head: str) -> None:
    """As a moved-base run starts, drop the feedback review has approved over, so `prepare`
    does not route to `rework` for it."""
    if (
        unit.feedback
        and unit.feedback_source is not FeedbackSource.CONFLICT
        and not unit.has_own_rework_input(head)
    ):
        store.set_feedback(unit.id, "")


def moved_base_units(
    inst: Installation, units: list[StoredUnit], holds: Holds | None = None
) -> set[str]:
    """The ids of the units owed a moved-base run, read from the repositories' branches."""
    holds = holds or Holds(inst)
    heads: dict[str, str] = {}

    def head_of(unit: StoredUnit) -> str:
        if unit.id not in heads:
            heads[unit.id] = _branch_head(inst.checkouts, unit)
        return heads[unit.id]

    def has_commits(unit: StoredUnit) -> bool:
        if not head_of(unit):
            return False
        base = local_ref(base_of(unit, units), repo=unit.repo)
        try:
            return branch_commits(inst.checkouts[unit.repo], base, _branch_of(unit)) > 0
        except Exception:  # noqa: BLE001 — an unresolvable ref is no commits, for a scan
            return False

    return {
        unit.id
        for unit in units
        if owed_a_moved_base_run(
            unit,
            units,
            has_commits=has_commits,
            head=head_of,
            held=holds.held,
            leased=holds.leased,
        )
    }


def base_tip(inst: Installation, unit: StoredUnit, units: list[StoredUnit]) -> str:
    """The commit the unit's base is at (the conflict handler's reading), empty when it cannot
    be read: the lane starts no run at a tip it cannot name."""
    try:
        return read_base_tip(inst.checkouts, unit, units)
    except Exception:  # noqa: BLE001 — an unreadable base is an empty tip, for the caller
        return ""


def attempts_at(unit: StoredUnit, tip: str) -> int:
    """How many attempts, the conflict handler's and the lane's, were made at base tip `tip`."""
    return unit.conflict_attempts if tip and unit.conflict_tip == tip else 0


def record_run_attempt(store: UnitStore, unit: StoredUnit, tip: str) -> None:
    """That a moved-base run starts: one more attempt at `tip`, with the head pushed now."""
    store.record_conflict_attempt(
        unit.id,
        tip=tip,
        head=unit.pushed or "",
        attempts=attempts_at(unit, tip) + 1,
        at=spans.clock.now(),
    )


def forget_run_attempt(store: UnitStore, before: StoredUnit) -> None:
    """That the run just recorded never got going: the unit's record is as `before` had it, and
    the run's resume is the attempt."""
    if before.conflict_attempts and before.conflict_at is not None:
        store.record_conflict_attempt(
            before.id,
            tip=before.conflict_tip,
            head=before.conflict_head,
            attempts=before.conflict_attempts,
            at=before.conflict_at,
        )
    else:
        store.clear_conflict_attempts(before.id)
    store.set_moved_base_uncounted(before.id, True)


def _last_ended(unit: StoredUnit) -> str:
    """How the unit's last run ended: the latest record in its history that a run wrote, not
    the unit's being owed one again (`base_changed`) nor its being started (`running`)."""
    for entry in reversed(unit.history):
        cause = Cause(entry["cause"]) if entry.get("cause") else None
        if entry["state"] != RUNNING and cause is not Cause.BASE_CHANGED:
            ended = str(entry["state"])
            return f"{ended} for {cause.value.replace('_', ' ')}" if cause else ended
    return str(unit.state)


def hold_if_spent(
    inst: Installation,
    store: UnitStore,
    unit: StoredUnit,
    units: list[StoredUnit],
    log: Callable[[str], None] = print,
) -> bool:
    """Hold, for a person, a unit whose attempts at its base's tip are spent, as the conflict
    handler does; whether it was held. A new tip starts the count at zero."""
    tip = base_tip(inst, unit, units)
    done = attempts_at(unit, tip)
    if done < active().global_limits.max_review_rounds:
        return False
    base = base_of(unit, units)
    note = (
        f"restack held: {done} attempts at {base}'s tip {tip[:12]} did not settle it; "
        f"the last ended {_last_ended(unit)}"
    )
    hold_for_conflict(unit, store, note, log, label="restack")
    return True


def owed_a_comment_rework(
    unit: StoredUnit,
    graph: list[StoredUnit],
    *,
    held: Callable[[StoredUnit], bool],
    leased: Callable[[StoredUnit], bool],
) -> bool:
    """Whether `unit` is owed a comment rework: in review or planned, sent back for rework with
    feedback, waiting on nothing, and neither leased nor held by a run."""
    return (
        unit.state in (PLANNED, IN_REVIEW)
        and unit.sent_back_for_rework
        and _free_to_run(unit, graph, held=held, leased=leased)
    )


def lane_runs_owed(
    inst: Installation, units: list[StoredUnit], holds: Holds | None = None
) -> set[str]:
    """The units owed a moved-base run or a comment rework that the lane's scan takes: not a
    moved-base run whose base tip cannot be read, which no run can be an attempt at."""
    holds = holds or Holds(inst)
    reworks = {
        unit.id
        for unit in units
        if owed_a_comment_rework(unit, units, held=holds.held, leased=holds.leased)
    }
    by_id = {unit.id: unit for unit in units}
    return reworks | {
        unit_id
        for unit_id in moved_base_units(inst, units, holds)
        if base_tip(inst, by_id[unit_id], units)
    }


def owed_units(inst: Installation, units: list[StoredUnit]) -> set[str]:
    """The ids of the units owed a restack, read from the repositories' branches, of those
    whose run the lane was making when it was interrupted, and of those owed a moved-base run
    or a comment rework."""
    holds = Holds(inst)
    held, leased = holds.held, holds.leased
    checkouts = inst.checkouts

    def holds_base(unit: StoredUnit) -> bool:
        repo = checkouts[unit.repo]
        branch = _branch_of(unit)
        if not _branch_head(checkouts, unit):
            return True  # No branch yet: there is nothing to move.
        base = local_ref(base_of(unit, units), repo=unit.repo)
        return is_ancestor(repo, base, branch)

    return {
        unit.id
        for unit in units
        if owed_a_restack(unit, units, holds_base=holds_base, held=held, leased=leased)
        or (in_a_lane_run(unit) and not leased(unit) and not held(unit))
    } | lane_runs_owed(inst, units, holds)


def record_path(state_dir: Path, key: ProjectKey) -> Path:
    """Where the lane of a project says what it holds, beside the other lanes' records."""
    name = f"{key.repo}/{key.project}".encode()
    return state_dir / f"restacks-{hashlib.sha256(name).hexdigest()[:12]}.json"


def lane_record(state_dir: Path) -> list[dict[str, str]]:
    """What the lanes of a live tick hold: each unit's `unit`, `base`, `status` (running or
    waiting) and `since`. A record whose process has gone is not trusted: nothing is held."""
    held: list[dict[str, str]] = []
    for path in sorted(state_dir.glob(RECORD_GLOB)):
        try:
            record = json.loads(path.read_text())
            pid, units = record["pid"], record["units"]
        except (OSError, ValueError, KeyError, TypeError):
            continue
        if isinstance(pid, int) and holder_alive(pid, record.get("host")):
            held.extend(entry for entry in units if isinstance(entry, dict))
    return held


def write_worker_record(
    state_dir: Path, key: ProjectKey, unit: StoredUnit, *, base: str, pid: int | None = None
) -> Path:
    """Say that the process `pid` (this one), a resolve worker, runs `unit`'s resolution run:
    the record the lanes of a tick write (`record_path`), so the run is read as the lane's
    (`lane_record`) while the process lives. Returns the record's path for
    `clear_worker_record`."""
    pid = os.getpid() if pid is None else pid
    # One file for each worker of the project: workers never overwrite or remove each other's.
    base_path = record_path(state_dir, key)
    path = base_path.with_name(f"{base_path.stem}-{pid}{base_path.suffix}")
    entry = {
        "unit": unit.id,
        "base": base,
        "resolving": unit.resolving,
        "status": "running",
        "since": spans.clock.now().isoformat(),
    }
    atomic_write_text(path, json.dumps({"pid": pid, "host": host.this_host(), "units": [entry]}))
    return path


def clear_worker_record(path: Path) -> None:
    """Remove a record `write_worker_record` wrote: the run it named has ended."""
    path.unlink(missing_ok=True)


def record_deferral(state_dir: Path, unit_id: str, resume_at: datetime) -> None:
    """Say that a refusal (a usage pause, a login) defers `unit_id`'s resolution run until
    `resume_at`: the dispatch starts no resolve worker for it before then."""
    path = _deferral_path(state_dir, unit_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, json.dumps({"unit": unit_id, "until": resume_at.isoformat()}))


def deferred_until(state_dir: Path, unit_id: str) -> datetime | None:
    """When the recorded deferral of `unit_id`'s run ends, or None when none is recorded."""
    try:
        record = json.loads(_deferral_path(state_dir, unit_id).read_text())
        return datetime.fromisoformat(record["until"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _deferral_path(state_dir: Path, unit_id: str) -> Path:
    name = hashlib.sha256(unit_id.encode()).hexdigest()[:16]
    return state_dir / "resolution-deferrals" / f"{name}.json"


def lane_held_by_record(state_dir: Path) -> set[str]:
    """The ids of the units the lanes of a live tick hold, running or waiting (`lane_record`)."""
    return {entry["unit"] for entry in lane_record(state_dir)}


def _admit_all(unit: StoredUnit) -> bool:
    return True


def _release_none(unit: StoredUnit) -> None:
    return None


def _wake_none(ended: ResolutionLane) -> None:
    return None


class _Entry:
    def __init__(
        self, unit: StoredUnit, work: Work, done: list[Callable[[bool], None]], claimed: bool
    ) -> None:
        self.unit, self.work, self.done, self.claimed = unit, work, done, claimed
        self.since = spans.clock.now().isoformat()


class ResolutionLane:
    """A pool of `cap` workers and a first-seen queue with one entry per unit. The bound is
    per project: `ResolutionLanes` holds one lane for each project of the workspace."""

    def __init__(
        self,
        cap: int,
        *,
        move: Move,
        claim: Claim,
        owed: Owed = lambda units: (),
        stamp: Stamp | None = None,
        paused: Callable[[], Collection[Hashable]] = lambda: (),
        record: Path | None = None,
        base: Callable[[StoredUnit], str] = lambda unit: "",
        runs: Callable[[StoredUnit], bool] = lambda unit: False,
        log: Callable[[str], None] = print,
    ) -> None:
        """`stamp` reads what a restack of the unit depends on (its branch head and base).
        A unit whose attempt left it as it was is not handed over again by `scan` until
        the stamp changes: a deferred move is not retried on a loop of its own, only when a
        usage pause that stood has ended. `paused` names the pauses in force, one key for each
        (an account's, or the network's): the moves are tried again when any key has left it,
        whatever the others do. `record` is where the lane says what it holds, each
        unit with the `base` it moves onto. `runs` says of a unit that the lane is making its whole
        run, which the scan hands over with no claim: the run takes the branch lock itself."""
        self._cap, self._move, self._claim, self._owed, self._log = cap, move, claim, owed, log
        self._stamp, self._paused, self._record, self._base = stamp, paused, record, base
        self._runs = runs
        self._was_paused: frozenset[Hashable] = frozenset()
        self._until: dict[str, datetime] = {}
        self._tried: dict[str, object] = {}
        self._changed = threading.Condition()
        self._queue: list[_Entry] = []
        self._running: dict[str, _Entry] = {}
        self._threads: list[threading.Thread] = []
        self._finished: Future[None] = Future()
        # What a lane of `ResolutionLanes` is bound to (`bind`): the account's admission of an
        # entry, the return of its place, and the wake of the other lanes when a worker ends. A
        # lane on its own admits every entry the project's cap allows.
        self._admit: Callable[[StoredUnit], bool] = _admit_all
        self._release: Callable[[StoredUnit], None] = _release_none
        self._wake: Callable[[ResolutionLane], None] = _wake_none

    def bind(
        self,
        admit: Callable[[StoredUnit], bool],
        release: Callable[[StoredUnit], None],
        wake: Callable[[ResolutionLane], None],
    ) -> None:
        """Hold this lane's starts to `admit`, which the lane calls with its own lock held, so it
        takes no lane's lock; `release` gives the place back, and `wake` runs, with no lock held,
        after a worker has ended, to start what the freed place lets in another lane."""
        self._admit, self._release, self._wake = admit, release, wake

    @property
    def full(self) -> bool:
        """Whether the project's cap of running restacks is reached."""
        with self._changed:
            return len(self._running) >= self._cap

    def note(self, message: str) -> None:
        """Say `message` in this lane's log, for the lanes that hold it."""
        self._log(message)

    def restart(self) -> None:
        """Start the queued restacks that a place freed elsewhere now lets in."""
        with self._changed:
            if self._queue:
                self._start()
                self._write()

    def hand_over(
        self,
        unit: StoredUnit,
        work: Work | None = None,
        *,
        done: Callable[[bool], None] | None = None,
        claimed: bool = True,
    ) -> None:
        """Queue `unit`'s restack once and start it before returning when a worker is free.

        `work` is what runs under the unit's branch claim (the lane's `move` of the unit
        when none is given); `done` runs after it with whether the work ran to the end, or
        with False when the unit could not be claimed. With `claimed` false the entry owns no
        claim: the work takes the branch lock itself, as a unit's run does."""
        with self._changed:
            seen = [*self._queue, *self._running.values()]
            known = next((entry for entry in seen if entry.unit.id == unit.id), None)
            if known is not None:
                if done:
                    known.done.append(done)
                return
            self._queue.append(
                _Entry(unit, work or (lambda: self._move(unit)), [done] if done else [], claimed)
            )
            self._start()
            self._write()

    def withdraw(self, unit: StoredUnit) -> bool:
        """Take the unit's queued entry out of the lane, for a build worker to run it instead;
        whether it was queued. A run already going in the lane stays."""
        with self._changed:
            for index, entry in enumerate(self._queue):
                if entry.unit.id == unit.id:
                    del self._queue[index]
                    self._write()
                    return True
        return False

    def scan(self, units: list[StoredUnit]) -> None:
        """Hand over every unit the lane's `owed` names that is not already queued."""
        self.scan_owed(units, set(self._owed(units)))

    def scan_owed(self, units: list[StoredUnit], owed: Collection[str]) -> None:
        """Hand over each of `units` that `owed` names and that is not already queued."""
        paused = frozenset(self._paused())
        if self._was_paused - paused:
            # A pause ended, whatever others still stand: what it left deferred is moved again,
            # asking the guard again (a unit of a pause that stands is deferred again).
            with self._changed:
                self._tried.clear()
                self._until.clear()
        self._was_paused = paused
        for unit in units:
            if unit.id in owed and not self._unchanged_since_tried(unit):
                self.hand_over(unit, claimed=not self._runs(unit))

    def defer_until(self, unit_id: str, resume_at: datetime | None) -> None:
        """The usage guard refused an agent call of the unit's move or run and expects to allow it
        from `resume_at`: `scan` does not hand the unit over again before then, and does once it
        has passed."""
        if resume_at is not None:
            with self._changed:
                self._until[unit_id] = resume_at

    def _unchanged_since_tried(self, unit: StoredUnit) -> bool:
        with self._changed:
            tried = self._tried.get(unit.id)
            until = self._until.get(unit.id)
            if until is not None and spans.clock.now() >= until:
                # The refusal's time has come: the same branch and base are tried again.
                del self._until[unit.id]
                self._tried.pop(unit.id, None)
                return False
        return self._stamp is not None and tried is not None and tried == self._stamp(unit)

    def drain(self) -> None:
        """Return once nothing is running or waiting."""
        with self._changed:
            self._changed.wait_for(lambda: not self._queue and not self._running)
            threads, self._threads = self._threads, []
        for thread in threads:
            thread.join()

    def finished(self) -> Future[Any]:
        """A future that completes when the next restack ends, for a loop to wait on; one
        already complete when nothing is running or waiting."""
        with self._changed:
            if not self._queue and not self._running:
                idle: Future[Any] = Future()
                idle.set_result(None)
                return idle
            return self._finished

    @property
    def running(self) -> list[str]:
        with self._changed:
            return list(self._running)

    @property
    def waiting(self) -> list[str]:
        with self._changed:
            return [entry.unit.id for entry in self._queue]

    def __enter__(self) -> ResolutionLane:
        return self

    def __exit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        trace: TracebackType | None,
    ) -> None:
        self.drain()

    def _start(self) -> None:
        """Start queued restacks, first seen first, while a worker is free and the account admits
        them; the caller holds the lock. An entry the account does not admit stays where it is and
        the next is tried, so it never holds back an entry of another account."""
        index = 0
        while index < len(self._queue) and len(self._running) < self._cap:
            entry = self._queue[index]
            if not self._admit(entry.unit):
                index += 1
                continue
            del self._queue[index]
            self._running[entry.unit.id] = entry
            # The tick's span goes into the worker by its context: a thread does not inherit it.
            context = contextvars.copy_context()
            thread = threading.Thread(
                target=context.run, args=(self._run, entry), name="resolve", daemon=True
            )
            try:
                thread.start()
            except BaseException:
                # No worker: the entry goes back, and its place with the account is returned.
                del self._running[entry.unit.id]
                self._queue.insert(index, entry)
                self._release(entry.unit)
                raise
            self._threads.append(thread)

    def _write(self) -> None:
        """Say what the lane holds; the caller holds the lock. A view: it never stops a restack."""
        if self._record is None:
            return
        held = [
            *(("running", entry) for entry in self._running.values()),
            *(("waiting", entry) for entry in self._queue),
        ]
        try:
            if not held:
                self._record.unlink(missing_ok=True)
                return
            units = [
                {
                    "unit": entry.unit.id,
                    "base": self._base(entry.unit),
                    "resolving": entry.unit.resolving,
                    "status": status,
                    "since": entry.since,
                }
                for status, entry in held
            ]
            atomic_write_text(
                self._record,
                json.dumps({"pid": os.getpid(), "host": host.this_host(), "units": units}),
            )
        except Exception as error:  # noqa: BLE001
            self._log(f"restack record not written — {type(error).__name__}: {error}")

    def _note_attempt(self, unit: StoredUnit) -> None:
        """Remember what the unit's restack met, so a scan leaves it until that changes."""
        if self._stamp is None:
            return
        try:
            stamp = self._stamp(unit)
        except Exception as error:  # noqa: BLE001 — a stamp that cannot be read never stops a restack
            self._log(f"{unit.id}: restack not noted — {type(error).__name__}: {error}")
            return
        with self._changed:
            self._tried[unit.id] = stamp

    def _go_on(self, entry: _Entry, rest: Rest) -> None:
        """Make the unit's run. One that went ahead is noted like a move, so a scan leaves it
        until its stamp changes; one that met a held branch (`BranchBusy`) is not, and is
        tried again."""
        try:
            rest()
        except BranchBusy:
            raise
        except BaseException:
            self._note_unclaimed(entry)
            raise
        self._note_unclaimed(entry)

    def _note_unclaimed(self, entry: _Entry) -> None:
        if not entry.claimed:
            self._note_attempt(entry.unit)

    def _run(self, entry: _Entry) -> None:
        unit = entry.unit
        ran = False
        spans.resolving.set(unit.resolving)
        try:
            if entry.claimed:
                with self._claim(unit):
                    try:
                        rest = entry.work()
                    finally:
                        self._note_attempt(unit)
            else:
                rest = entry.work()
            # What remains is the unit's run: it holds this worker, not the claim.
            if rest is not None:
                self._go_on(entry, rest)
            ran = True
        except BranchBusy as error:
            self._log(f"{unit.id}: restack left for later, its branch is held ({error})")
        except Exception as error:  # noqa: BLE001 — one restack never ends the lane
            self._log(f"{unit.id}: restack failed — {type(error).__name__}: {error}")
        finally:
            for done in entry.done:
                try:
                    done(ran)
                except Exception as error:  # noqa: BLE001
                    self._log(f"{unit.id}: after its restack — {type(error).__name__}: {error}")
            with self._changed:
                del self._running[unit.id]
                self._release(unit)
                try:
                    self._start()
                except Exception as error:  # noqa: BLE001 — no worker for the next entry
                    # The entry stays queued and its place is returned (`_start`); the waiters
                    # below are still told and the other lanes still woken, or they would wait on
                    # a restack that has ended.
                    self._log(f"restack not started — {type(error).__name__}: {error}")
                self._write()
                self._changed.notify_all()
                ended, self._finished = self._finished, Future()
            try:
                # With no lock of this lane held: another lane's lock is taken in turn, never two
                # at once, so two lanes ending together cannot wait on each other.
                self._wake(self)
            finally:
                ended.set_result(None)


class ResolutionLanes:
    """A lane for each project, made on first use by `make` and routed to by a unit's project.

    The bound of a lane is per project: two projects of one repo each run up to the cap, and a
    full lane never holds back a restack of another project. An account that sets a cap
    (`account_cap`, for the account `account_of` names for a unit) is held to it across its
    projects as well: the lanes count the account's running restacks under their guard, a lane
    starts an entry only when the account admits it, and a worker that ends restarts the waiting
    entries of the other lanes. An account with no cap, as the default account has none, adds none.

    The locks: each lane has its own and the lanes one guard, and a lane takes the guard while it
    holds its own, never the other way round and never two lanes' locks at once. The guard is
    held only to read or change a count."""

    def __init__(
        self,
        make: Callable[[ProjectKey], ResolutionLane],
        *,
        owed: Owed = lambda units: (),
        account_of: Callable[[StoredUnit], Hashable] = lambda unit: None,
        account_cap: Callable[[Hashable], int | None] = lambda account: None,
    ) -> None:
        self._make, self._owed = make, owed
        self._account_of, self._account_cap = account_of, account_cap
        self._guard = threading.Lock()
        self._lanes: dict[ProjectKey, ResolutionLane] = {}
        self._account_running: dict[Hashable, int] = {}

    def _lane(self, key: ProjectKey) -> ResolutionLane:
        with self._guard:
            if key not in self._lanes:
                lane = self._make(key)
                lane.bind(self._admit, self._give_back, self._wake)
                self._lanes[key] = lane
            return self._lanes[key]

    def _admit(self, unit: StoredUnit) -> bool:
        """Count a restack of `unit` against its account when the account has room; called by a
        lane with its own lock held."""
        account = self._account_of(unit)
        cap = self._account_cap(account)
        with self._guard:
            running = self._account_running.get(account, 0)
            if cap is not None and running >= cap:
                return False
            self._account_running[account] = running + 1
            return True

    def _give_back(self, unit: StoredUnit) -> None:
        account = self._account_of(unit)
        with self._guard:
            left = self._account_running.get(account, 0) - 1
            if left > 0:
                self._account_running[account] = left
            else:
                self._account_running.pop(account, None)

    def _wake(self, ended: ResolutionLane) -> None:
        """A place was freed: the other lanes try their waiting entries again. Each lane's lock is
        taken alone, after the count was changed, so an entry a lane refused before the change is
        met by this restart, and one it meets after is admitted by its own start. The ending lane
        starts its own queue first, so a place goes to it before the waiting entries of the other
        lanes: a lane with a continuous backlog can retake the places it frees."""
        for lane in self._all():
            if lane is not ended:
                try:
                    lane.restart()
                except Exception as error:  # noqa: BLE001 — one lane's failure leaves the rest
                    ended.note(f"restack not restarted — {type(error).__name__}: {error}")

    def lane_full(self, unit: StoredUnit) -> bool:
        """Whether the lane of the unit's project has all its workers busy. A lane nothing has
        handed to is not made by the question and is not full."""
        with self._guard:
            lane = self._lanes.get(project_key(unit))
        return lane is not None and lane.full

    def account_full(self, unit: StoredUnit) -> bool:
        """Whether the unit's account runs as many restacks, across its projects, as it allows;
        an account with no cap is never full."""
        account = self._account_of(unit)
        cap = self._account_cap(account)
        with self._guard:
            return cap is not None and self._account_running.get(account, 0) >= cap

    def at_cap(self, unit: StoredUnit) -> bool:
        """Whether a restack of the unit would have to wait now, for its project's lane or for its
        account. It is a reading at one moment: a restack may start or end the next."""
        return self.lane_full(unit) or self.account_full(unit)

    def _all(self) -> list[ResolutionLane]:
        with self._guard:
            return list(self._lanes.values())

    def hand_over(
        self,
        unit: StoredUnit,
        work: Work | None = None,
        *,
        done: Callable[[bool], None] | None = None,
        claimed: bool = True,
    ) -> None:
        self._lane(project_key(unit)).hand_over(unit, work, done=done, claimed=claimed)

    def withdraw(self, unit: StoredUnit) -> bool:
        """Take the unit's queued entry out of its project's lane (`ResolutionLane.withdraw`)."""
        with self._guard:
            lane = self._lanes.get(project_key(unit))
        return lane is not None and lane.withdraw(unit)

    def scan(self, units: list[StoredUnit]) -> None:
        """Hand each owed unit to the lane of its project, making that lane if need be."""
        owed = set(self._owed(units))
        keys = {project_key(unit) for unit in units if unit.id in owed}
        with self._guard:
            keys |= set(self._lanes)
        for key in keys:
            mine = [unit for unit in units if project_key(unit) == key]
            self._lane(key).scan_owed(mine, owed)

    def defer_until(self, unit_id: str, resume_at: datetime | None) -> None:
        for lane in self._all():
            lane.defer_until(unit_id, resume_at)

    def drain(self) -> None:
        """Return once nothing is running or waiting in any lane."""
        while True:
            for lane in self._all():
                lane.drain()
            if not any(lane.running or lane.waiting for lane in self._all()):
                return

    def finished(self) -> Future[Any]:
        """A future that completes when the next restack of any lane ends; one already
        complete when no lane has work."""
        ends: Future[Any] = Future()
        pending = [future for lane in self._all() if not (future := lane.finished()).done()]
        if not pending:
            ends.set_result(None)
            return ends

        def settle(_: Future[Any]) -> None:
            with self._guard:
                if not ends.done():
                    ends.set_result(None)

        for future in pending:
            future.add_done_callback(settle)
        return ends

    @property
    def running(self) -> list[str]:
        return [unit for lane in self._all() for unit in lane.running]

    @property
    def waiting(self) -> list[str]:
        return [unit for lane in self._all() for unit in lane.waiting]

    def __enter__(self) -> ResolutionLanes:
        return self

    def __exit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        trace: TracebackType | None,
    ) -> None:
        self.drain()


Lane = ResolutionLane | ResolutionLanes
