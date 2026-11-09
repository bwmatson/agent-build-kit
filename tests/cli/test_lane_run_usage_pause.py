"""A moved-base run a usage pause interrupts at the port stays the lane's: the unit is `running`,
flagged, its thread at the port; the lane retries it neither before the guard's `resume_at` nor on
a timer, and the scan after the pause resumes it at the port, asking the guard again (spec:
restack-conflicts, the port under a pause).

The scene is `tests/lane_run_usage_support.py`'s. The guard reads the faked usage endpoint and the
clock is the test's, so a retry before `resume_at` is one the test can see.
"""

from __future__ import annotations

from collections.abc import Callable

from agent_build_kit.graph.state import Node
from agent_build_kit.pipeline.units import RUNNING
from tests.lane_run_usage_support import RESOLVER_CALLS, Lane, make_lane  # noqa: F401 — fixture
from tests.tick_driver import OTHER


def paused_at_the_port(make_lane: Callable[..., Lane]) -> Lane:  # noqa: F811 — fixture
    """The lane's run, met by a pause after the resolver's two calls, which stops it at the port."""
    lane = make_lane()
    lane.runtime.after = lambda number: lane.shut() if number == RESOLVER_CALLS else None
    lane.open()
    return lane


def stops_at_the_port(lane: Lane, attempts: int = 0) -> None:
    stored = lane.graph.store.get(OTHER)
    assert (stored.state, stored.moved_base_run) == (RUNNING, True)
    assert lane.graph.next(OTHER) == (Node.ADAPT,), "its thread stands at the port"
    assert stored.conflict_attempts == attempts
