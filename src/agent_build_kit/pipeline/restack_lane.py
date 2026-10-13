"""The lane restacks run in: its own workers, apart from the build pool.

A restack is the part of a unit's flow whose only cause is that its base moved.
It takes no build slot, starts when it is seen, and runs in the order it was
seen, at most `limits.max_concurrent_restacks` at once. The lane holds no turn
of its own: the move takes the repository's turn for the phases that write shared
git state.
"""

from __future__ import annotations

import contextvars
import json
import os
import threading
from collections.abc import Callable, Collection
from concurrent.futures import Future
from pathlib import Path
from types import TracebackType
from typing import Any

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline import spans
from agent_build_kit.pipeline.events import Claim
from agent_build_kit.pipeline.lease import Leases, lease_dir
from agent_build_kit.pipeline.shell import git
from agent_build_kit.pipeline.unit_store import Cause, StoredUnit
from agent_build_kit.pipeline.units import (
    IN_REVIEW,
    PLANNED,
    RUNNING,
    base_of,
    branch_name,
    local_ref,
    waiting_on,
)
from agent_build_kit.pipeline.wiring import is_ancestor
from agent_build_kit.pipeline.workspaces import BranchBusy, branch_held, process_alive

Move = Callable[[StoredUnit], None]
Work = Callable[[], None]
Owed = Callable[[list[StoredUnit]], Collection[str]]
Stamp = Callable[[StoredUnit], object]

# The lane's record in the state directory, for `abk status` and the graph page, which are
# not the process that runs the tick.
RECORD_NAME = "restacks.json"

OWED_STATES = (PLANNED, RUNNING, IN_REVIEW)
OWED_CAUSES = (Cause.BASE_CHANGED, Cause.RESTACK_DEFERRED)


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
    return (
        unit.state in OWED_STATES
        and unit.cause in OWED_CAUSES
        and not waiting_on(unit, graph)
        and not leased(unit)
        and not held(unit)
        and not holds_base(unit)
    )


def owed_units(inst: Installation, units: list[StoredUnit]) -> set[str]:
    """The ids of the units owed a restack, read from the repositories' branches."""
    leases = Leases(lease_dir(inst.state_dir))
    checkouts = inst.checkouts

    def branch_of(unit: StoredUnit) -> str:
        return unit.branch or branch_name(unit)

    def holds_base(unit: StoredUnit) -> bool:
        repo = checkouts[unit.repo]
        branch = branch_of(unit)
        if (
            not repo.is_dir()
            or git(repo, "rev-parse", "--verify", "--quiet", branch, check=False).returncode
        ):
            return True  # No branch yet: there is nothing to move.
        base = local_ref(base_of(unit, units), repo=unit.repo)
        return is_ancestor(repo, base, branch)

    return {
        unit.id
        for unit in units
        if owed_a_restack(
            unit,
            units,
            holds_base=holds_base,
            held=lambda unit: branch_held(branch_of(unit), root=inst.state_dir / "locks"),
            leased=lambda unit: leases.holder(unit.id) is not None,
        )
    }


def lane_record(state_dir: Path) -> list[dict[str, str]]:
    """What the lane of a live tick holds: each unit's `unit`, `base`, `status` (running or
    waiting) and `since`. A record whose process has gone is not trusted: nothing is held."""
    try:
        record = json.loads((state_dir / RECORD_NAME).read_text())
        pid, units = record["pid"], record["units"]
    except (OSError, ValueError, KeyError, TypeError):
        return []
    if not isinstance(pid, int) or not process_alive(pid):
        return []
    return [entry for entry in units if isinstance(entry, dict)]


class _Entry:
    def __init__(self, unit: StoredUnit, work: Work, done: list[Callable[[bool], None]]) -> None:
        self.unit, self.work, self.done = unit, work, done
        self.since = spans.clock.now().isoformat()


class RestackLane:
    """A pool of `cap` workers and a first-seen queue with one entry per unit."""

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
        log: Callable[[str], None] = print,
    ) -> None:
        """`stamp` reads what a restack of the unit depends on (its branch head and base).
        A unit whose attempt left it as it was is not handed over again by `scan` until
        the stamp changes: a deferred move is not retried on a loop of its own, only when a
        usage pause that stood has ended. `record` is where the lane says what it holds, each
        unit with the `base` it moves onto."""
        self._cap, self._move, self._claim, self._owed, self._log = cap, move, claim, owed, log
        self._stamp, self._paused, self._record, self._base = stamp, paused, record, base
        self._was_paused = False
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
    ) -> None:
        """Queue `unit`'s restack once and start it before returning when a worker is free.

        `work` is what runs under the unit's branch claim (the lane's `move` of the unit
        when none is given); `done` runs after it with whether the work ran to the end, or
        with False when the unit could not be claimed."""
        with self._changed:
            seen = [*self._queue, *self._running.values()]
            known = next((entry for entry in seen if entry.unit.id == unit.id), None)
            if known is not None:
                if done:
                    known.done.append(done)
                return
            self._queue.append(
                _Entry(unit, work or (lambda: self._move(unit)), [done] if done else [])
            )
            self._start()
            self._write()

    def scan(self, units: list[StoredUnit]) -> None:
        """Hand over every unit the lane's `owed` names that is not already queued."""
        if self._paused():
            self._was_paused = True
        elif self._was_paused:
            # The pause ended: what it left deferred is moved again, asking the guard again.
            self._was_paused = False
            with self._changed:
                self._tried.clear()
        owed = set(self._owed(units))
        for unit in units:
            if unit.id in owed and not self._unchanged_since_tried(unit):
                self.hand_over(unit)

    def _unchanged_since_tried(self, unit: StoredUnit) -> bool:
        with self._changed:
            tried = self._tried.get(unit.id)
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
            partial = self._record.with_name(f"{self._record.name}.{os.getpid()}.tmp")
            partial.write_text(json.dumps({"pid": os.getpid(), "units": units}))
            os.replace(partial, self._record)
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

    def _run(self, entry: _Entry) -> None:
        unit = entry.unit
        ran = False
        try:
            with self._claim(unit):
                try:
                    entry.work()
                    ran = True
                finally:
                    self._note_attempt(unit)
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
