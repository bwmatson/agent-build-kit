"""What the restack lane's tests share: restacks that block on events, and a lane over
the real branch locks, so a claim held by a run is the one the lane meets."""

from __future__ import annotations

import threading
from collections.abc import Callable, Collection
from pathlib import Path
from typing import Any

from agent_build_kit.pipeline.events import build_claim
from agent_build_kit.pipeline.restack_lane import RestackLane
from agent_build_kit.pipeline.unit_store import Cause, StoredUnit
from tests.factories import stored_unit

WAIT = 60


def units(count: int) -> list[StoredUnit]:
    return [stored_unit(f"feature/{number}", change="feature") for number in range(1, count + 1)]


def caused(unit_id: str, state: str, cause: Cause | None, **fields: Any) -> StoredUnit:
    """A stored unit in `state` whose last change out of running had `cause`, as the
    store records it in the unit's history."""
    history = (
        ({"state": state, "at": "2026-01-01T00:00:00+00:00", "cause": cause.value},)
        if cause
        else ()
    )
    return stored_unit(unit_id, change="feature", state=state, history=history, **fields)


class Events(dict[str, threading.Event]):
    """An event for each unit id, made when first asked for."""

    mutex = threading.Lock()

    def __missing__(self, unit_id: str) -> threading.Event:
        with self.mutex:
            return self.setdefault(unit_id, threading.Event())


class Restacks:
    """The lane's `move`: each unit's restack starts, notes it, and ends when released."""

    def __init__(self) -> None:
        self.started: list[str] = []
        self.finished: list[str] = []
        self.begun = Events()
        self.released = Events()
        self.mutex = threading.Lock()
        self.at_once = 0
        self.most_at_once = 0
        self.everything = False

    def __call__(self, unit: StoredUnit) -> None:
        with self.mutex:
            self.started.append(unit.id)
            self.at_once += 1
            self.most_at_once = max(self.most_at_once, self.at_once)
        self.begun[unit.id].set()
        assert self.everything or self.released[unit.id].wait(WAIT)
        with self.mutex:
            self.at_once -= 1
            self.finished.append(unit.id)

    def release(self, *unit_ids: str) -> None:
        for unit_id in unit_ids:
            self.released[unit_id].set()

    def release_all(self) -> None:
        """Every restack, those not yet started as well."""
        self.everything = True
        for event in list(self.released.values()):
            event.set()


def lane_over(
    locks: Path,
    move: Callable[[StoredUnit], None],
    *,
    cap: int = 2,
    owed: Callable[[list[StoredUnit]], Collection[str]] = lambda graph: (),
) -> RestackLane:
    return RestackLane(cap, move=move, claim=build_claim(locks), owed=owed)
