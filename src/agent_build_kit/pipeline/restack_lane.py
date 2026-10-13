"""The lane restacks run in: its own workers, apart from the build pool.

A restack is the part of a unit's flow whose only cause is that its base moved.
It takes no build slot, starts when it is seen, and runs in the order it was
seen, at most `limits.max_concurrent_restacks` at once. The lane holds no turn
of its own: the move takes the repository's turn for the phases that write shared
git state.
"""

from __future__ import annotations

import contextvars
import threading
from collections.abc import Callable, Collection
from concurrent.futures import Future
from types import TracebackType
from typing import Any

from agent_build_kit.installation import Installation
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
from agent_build_kit.pipeline.workspaces import BranchBusy, branch_held

Move = Callable[[StoredUnit], None]
Work = Callable[[], None]
Owed = Callable[[list[StoredUnit]], Collection[str]]

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
        return not git(repo, "merge-base", "--is-ancestor", base, branch, check=False).returncode

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


class _Entry:
    def __init__(self, unit: StoredUnit, work: Work, done: list[Callable[[], None]]) -> None:
        self.unit, self.work, self.done = unit, work, done


class RestackLane:
    """A pool of `cap` workers and a first-seen queue with one entry per unit."""

    def __init__(
        self,
        cap: int,
        *,
        move: Move,
        claim: Claim,
        owed: Owed = lambda units: (),
        log: Callable[[str], None] = print,
    ) -> None:
        self._cap, self._move, self._claim, self._owed, self._log = cap, move, claim, owed, log
        self._changed = threading.Condition()
        self._queue: list[_Entry] = []
        self._running: dict[str, _Entry] = {}
        self._threads: list[threading.Thread] = []
        self._finished: Future[None] = Future()

    def hand_over(
        self, unit: StoredUnit, work: Work | None = None, *, done: Callable[[], None] | None = None
    ) -> None:
        """Queue `unit`'s restack once and start it before returning when a worker is free.

        `work` is what runs under the unit's branch claim (the lane's `move` of the unit
        when none is given); `done` runs after it, or when the unit could not be claimed."""
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

    def scan(self, units: list[StoredUnit]) -> None:
        """Hand over every unit the lane's `owed` names that is not already queued."""
        owed = set(self._owed(units))
        for unit in units:
            if unit.id in owed:
                self.hand_over(unit)

    def drain(self) -> None:
        """Return once nothing is running or waiting."""
        with self._changed:
            self._changed.wait_for(lambda: not self._queue and not self._running)
            threads, self._threads = self._threads, []
        for thread in threads:
            thread.join()

    def finished(self) -> Future[Any]:
        """A future that completes when the next restack ends, for a loop to wait on."""
        with self._changed:
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

    def _run(self, entry: _Entry) -> None:
        unit = entry.unit
        try:
            with self._claim(unit):
                entry.work()
        except BranchBusy as error:
            self._log(f"{unit.id}: restack left for later, its branch is held ({error})")
        except Exception as error:  # noqa: BLE001 — one restack never ends the lane
            self._log(f"{unit.id}: restack failed — {type(error).__name__}: {error}")
        finally:
            for done in entry.done:
                try:
                    done()
                except Exception as error:  # noqa: BLE001
                    self._log(f"{unit.id}: after its restack — {type(error).__name__}: {error}")
            with self._changed:
                del self._running[unit.id]
                self._start()
                self._changed.notify_all()
                ended, self._finished = self._finished, Future()
            ended.set_result(None)
