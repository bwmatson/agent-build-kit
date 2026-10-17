"""Every agent call of a moved-base run in the lane is asked of the usage guard, the resolver of
the run's own move as well as the port and the review (spec: restack-conflicts, a restack in the
lane honours the usage guard for its agent step).

The guard is the real one over the faked usage endpoint; the move is faked at `restack_onto`'s
edge (`tests/lane_run_usage_support.py`).
"""

from __future__ import annotations

import json
from collections.abc import Callable

from agent_build_kit.pipeline.unit_store import Cause
from agent_build_kit.pipeline.units import FAILED, HELD
from tests.lane_run_usage_support import MINUTE, Lane, make_lane  # noqa: F401 — fixture
from tests.tick_driver import OTHER
from tests.usage_host import Host, payload, refused


def admitted(host: Host) -> list[str]:
    return json.loads(host.cache.read_text()).get("estimate_units", [])


def test_under_a_pause_a_conflict_in_the_move_is_not_resolved_and_defers_the_run(
    make_lane: Callable[..., Lane],  # noqa: F811 — fixture
) -> None:
    lane = make_lane()
    lane.shut()

    lane.scene.lane_moves()

    assert lane.runtime.requests == [], "the resolver was called under a pause"
    assert [decision.may_start for decision in lane.decisions] == [False]
    stored = lane.graph.store.get(OTHER)
    assert stored.state not in (FAILED, HELD), "a refusal is not a failure"
    assert stored.cause is Cause.RESTACK_DEFERRED
    assert stored.conflict_attempts == 0, "a run deferred before its first agent call is no attempt"


def test_a_refused_read_with_room_on_the_estimate_admits_every_call_of_the_run_for_the_unit(
    make_lane: Callable[..., Lane],  # noqa: F811 — fixture
) -> None:
    lane = make_lane()
    lane.host.keep_reading(89 * MINUTE, payload(session=52.0, weekly=52.0))
    refused(lane.host, cooling=3 * MINUTE)

    lane.scene.lane_moves()

    # The resolver's two calls, the port and the review of the result, each asked once.
    assert len(lane.runtime.requests) == 4
    assert [decision.may_start for decision in lane.decisions] == [True] * 4
    assert admitted(lane.host) == [OTHER], "the admission names the unit moved"
