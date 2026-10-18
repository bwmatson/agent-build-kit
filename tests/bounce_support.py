"""A unit put back by the same cause again and again, written through the store."""

from __future__ import annotations

from agent_build_kit.pipeline.unit_store import Cause, UnitStore
from agent_build_kit.pipeline.units import PLANNED, RUNNING, UnitState
from tests.fake_clock import FakeClock


def bounce(
    store: UnitStore,
    uid: str,
    cause: Cause | None,
    clock: FakeClock,
    *,
    seconds: float = 30,
    to: UnitState = PLANNED,
    note: str = "",
) -> None:
    """Run the unit for `seconds`, then put it back to `to` with `cause`."""
    store.set_state(uid, RUNNING, branch=f"spec/{uid}")
    clock.advance(seconds)
    store.set_state(uid, to, cause=cause, note=note)


def bounce_times(
    store: UnitStore, uid: str, cause: Cause, clock: FakeClock, times: int, **kw
) -> None:
    for _ in range(times):
        bounce(store, uid, cause, clock, **kw)
