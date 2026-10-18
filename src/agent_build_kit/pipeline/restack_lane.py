"""The lane restacks run in: its own workers, apart from the build pool.

A restack is the part of a unit's flow whose only cause is that its base moved.
It takes no build slot, starts when it is seen, and runs in the order it was
seen, at most `project_limits.max_concurrent_restacks` at once. The lane holds no turn
of its own: the move takes the repository's turn for the phases that write shared
git state.
"""

from __future__ import annotations

import contextvars
import hashlib
import json
import os
import threading
from collections.abc import Callable, Collection, Mapping
from concurrent.futures import Future
from datetime import datetime
from pathlib import Path
from types import TracebackType
from typing import Any

from agent_build_kit.config import active
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline import spans
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
from agent_build_kit.pipeline.workspaces import BranchBusy, branch_held, process_alive

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
MOVED_BASE_CAUSES = (*OWED_CAUSES, Cause.RESTACK_CONFLICT, Cause.RESTACK_HANDED_BACK)


def in_a_lane_run(unit: StoredUnit) -> bool:
    """Whether the lane is making the unit's whole run, so it is the lane's to resume."""
    return unit.state == RUNNING and unit.moved_base_run


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
        and not waiting_on(unit, graph)
        and not leased(unit)
        and not held(unit)
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
        and (unit.cause in MOVED_BASE_CAUSES or unit.sent_back_for_conflict)
        and not waiting_on(unit, graph)
        and not leased(unit)
        and not held(unit)
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


def moved_base_units(inst: Installation, units: list[StoredUnit]) -> set[str]:
    """The ids of the units owed a moved-base run, read from the repositories' branches."""
    leases = Leases(lease_dir(inst.state_dir))
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
            held=lambda unit: branch_held(_branch_of(unit), root=inst.state_dir / "locks"),
            leased=lambda unit: leases.holder(unit.id) is not None,
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


def lane_runs_owed(inst: Installation, units: list[StoredUnit]) -> set[str]:
    """The units owed a moved-base run that the lane's scan takes: not one it handed back, which a
    build worker takes from its step until its base moves again, and not one whose base tip
    cannot be read, which no run can be an attempt at."""
    by_id = {unit.id: unit for unit in units}
    return {
        unit_id
        for unit_id in moved_base_units(inst, units)
        if by_id[unit_id].cause is not Cause.RESTACK_HANDED_BACK
        and base_tip(inst, by_id[unit_id], units)
    }


def owed_units(inst: Installation, units: list[StoredUnit]) -> set[str]:
    """The ids of the units owed a restack, read from the repositories' branches, of those
    whose run the lane was making when it was interrupted, and of those owed a moved-base run."""
    leases = Leases(lease_dir(inst.state_dir))
    checkouts = inst.checkouts

    def holds_base(unit: StoredUnit) -> bool:
        repo = checkouts[unit.repo]
        branch = _branch_of(unit)
        if not _branch_head(checkouts, unit):
            return True  # No branch yet: there is nothing to move.
        base = local_ref(base_of(unit, units), repo=unit.repo)
        return is_ancestor(repo, base, branch)

    def held(unit: StoredUnit) -> bool:
        return branch_held(_branch_of(unit), root=inst.state_dir / "locks")

    def leased(unit: StoredUnit) -> bool:
        return leases.holder(unit.id) is not None

    return {
        unit.id
        for unit in units
        if owed_a_restack(unit, units, holds_base=holds_base, held=held, leased=leased)
        or (in_a_lane_run(unit) and not leased(unit) and not held(unit))
    } | lane_runs_owed(inst, units)


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
        if isinstance(pid, int) and process_alive(pid):
            held.extend(entry for entry in units if isinstance(entry, dict))
    return held


class _Entry:
    def __init__(
        self, unit: StoredUnit, work: Work, done: list[Callable[[bool], None]], claimed: bool
    ) -> None:
        self.unit, self.work, self.done, self.claimed = unit, work, done, claimed
        self.since = spans.clock.now().isoformat()


class RestackLane:
    """A pool of `cap` workers and a first-seen queue with one entry per unit. The bound is
    per project: `RestackLanes` holds one lane for each project of the workspace."""

    def __init__(
        self,
        cap: int,
        *,
        move: Move,
        claim: Claim,
        owed: Owed = lambda units: (),
        stamp: Stamp | None = None,
        paused: Callable[[], bool] = lambda: False,
        record: Path | None = None,
        base: Callable[[StoredUnit], str] = lambda unit: "",
        runs: Callable[[StoredUnit], bool] = lambda unit: False,
        log: Callable[[str], None] = print,
    ) -> None:
        """`stamp` reads what a restack of the unit depends on (its branch head and base).
        A unit whose attempt left it as it was is not handed over again by `scan` until
        the stamp changes: a deferred move is not retried on a loop of its own, only when a
        usage pause that stood has ended. `record` is where the lane says what it holds, each
        unit with the `base` it moves onto. `runs` says of a unit that the lane is making its whole
        run, which the scan hands over with no claim: the run takes the branch lock itself."""
        self._cap, self._move, self._claim, self._owed, self._log = cap, move, claim, owed, log
        self._stamp, self._paused, self._record, self._base = stamp, paused, record, base
        self._runs = runs
        self._was_paused = False
        self._until: dict[str, datetime] = {}
        self._tried: dict[str, object] = {}
        self._changed = threading.Condition()
        self._queue: list[_Entry] = []
        self._running: dict[str, _Entry] = {}
        self._threads: list[threading.Thread] = []
        self._finished: Future[None] = Future()

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

    def scan(self, units: list[StoredUnit]) -> None:
        """Hand over every unit the lane's `owed` names that is not already queued."""
        self.scan_owed(units, set(self._owed(units)))

    def scan_owed(self, units: list[StoredUnit], owed: Collection[str]) -> None:
        """Hand over each of `units` that `owed` names and that is not already queued."""
        if self._paused():
            self._was_paused = True
        elif self._was_paused:
            # The pause ended: what it left deferred is moved again, asking the guard again.
            self._was_paused = False
            with self._changed:
                self._tried.clear()
                self._until.clear()
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

    def __enter__(self) -> RestackLane:
        return self

    def __exit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        trace: TracebackType | None,
    ) -> None:
        self.drain()

    def _start(self) -> None:
        """Start queued restacks while a worker is free; the caller holds the lock."""
        while self._queue and len(self._running) < self._cap:
            entry = self._queue.pop(0)
            self._running[entry.unit.id] = entry
            # The tick's span goes into the worker by its context: a thread does not inherit it.
            context = contextvars.copy_context()
            thread = threading.Thread(
                target=context.run, args=(self._run, entry), name="restack", daemon=True
            )
            self._threads.append(thread)
            thread.start()

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
                    "status": status,
                    "since": entry.since,
                }
                for status, entry in held
            ]
            atomic_write_text(self._record, json.dumps({"pid": os.getpid(), "units": units}))
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
                self._start()
                self._write()
                self._changed.notify_all()
                ended, self._finished = self._finished, Future()
            ended.set_result(None)


class RestackLanes:
    """A lane for each project, made on first use by `make` and routed to by a unit's project.

    The bound of a lane is per project: two projects of one repo each run up to the cap, and a
    full lane never holds back a restack of another project."""

    def __init__(
        self, make: Callable[[ProjectKey], RestackLane], *, owed: Owed = lambda units: ()
    ) -> None:
        self._make, self._owed = make, owed
        self._guard = threading.Lock()
        self._lanes: dict[ProjectKey, RestackLane] = {}

    def _lane(self, key: ProjectKey) -> RestackLane:
        with self._guard:
            if key not in self._lanes:
                self._lanes[key] = self._make(key)
            return self._lanes[key]

    def _all(self) -> list[RestackLane]:
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

    def __enter__(self) -> RestackLanes:
        return self

    def __exit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        trace: TracebackType | None,
    ) -> None:
        self.drain()


Lane = RestackLane | RestackLanes
