"""Every agent call of a moved-base run in the lane is asked of the usage guard, the resolver of
the run's own move as well as the port and the review (spec: restack-conflicts, a restack in the
lane honours the usage guard for its agent step).

The guard is the real one over the faked usage endpoint; the move is faked at `restack_onto`'s
edge (`tests/lane_run_usage_support.py`).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import timedelta

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.graph.state import Node
from agent_build_kit.pipeline import spans
from agent_build_kit.pipeline.unit_store import Cause, FeedbackSource
from agent_build_kit.pipeline.units import FAILED, HELD, IN_REVIEW, RUNNING
from tests.factories import git
from tests.graph.test_adapt_in_the_restack_session import Failing
from tests.graph.test_restack_lane_prepare import BRANCH
from tests.lane_run_usage_support import MINUTE, Lane, make_lane  # noqa: F401 — fixture
from tests.restack_lane_fakes import Moving
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
    assert (stored.state, stored.cause) == (RUNNING, Cause.RESTACK_DEFERRED)
    assert stored.conflict_attempts == 0, "a run deferred before its first agent call is no attempt"
    assert lane.graph.next(OTHER) == (Node.PREPARE,), "the thread is left where it was"


def test_the_deferred_move_is_made_again_once_the_guard_allows_it(
    make_lane: Callable[..., Lane],  # noqa: F811 — fixture
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = Moving()
    monkeypatch.setattr(spans, "clock", clock)
    lane = make_lane()
    graph = lane.graph
    lane.shut()

    with cli.build_restack_lane(graph.inst, graph.store) as running:
        lane.scene.lane = running
        running.scan(graph.store.all())
        running.drain()
        asked = len(lane.decisions)
        resume_at = lane.decisions[-1].resume_at
        assert resume_at is not None and lane.runtime.requests == []

        # Room again, but the guard's time has not come: nothing is tried.
        lane.open()
        running.scan(graph.store.all())
        running.drain()
        assert len(lane.decisions) == asked, "retried before the guard expected to allow it"

        graph.options["restack_onto"] = lane.scene.restack(Failing())
        clock.set(resume_at + timedelta(seconds=1))
        running.scan(graph.store.all())
        running.drain()

    assert len(lane.decisions) > asked, "the guard was asked again"
    assert len(lane.runtime.requests) > 0, "and the resolver ran"
    assert graph.store.get(OTHER).state == IN_REVIEW, "the run went on"


def test_a_move_that_applies_cleanly_under_a_pause_is_made_in_the_lane_and_not_asked(
    make_lane: Callable[..., Lane],  # noqa: F811 — fixture
) -> None:
    lane = make_lane(conflict=False)
    lane.shut()

    lane.scene.lane_moves()

    assert git(lane.scene.repo, "merge-base", "--is-ancestor", "main", BRANCH) == ""
    assert lane.scene.calls and all(lane.scene.calls), "the move ran in the lane"
    assert lane.runtime.requests == []
    # Only the review of the result, which is an agent call, was put to the guard.
    assert [decision.may_start for decision in lane.decisions] == [False]
    assert lane.graph.next(OTHER) == (Node.REVIEW,), "and the run waits at it"


def test_a_conflict_rework_in_the_lane_is_asked_of_the_guard_for_the_unit(
    make_lane: Callable[..., Lane],  # noqa: F811 — fixture
) -> None:
    lane = make_lane(conflict=False)
    lane.host.keep_reading(89 * MINUTE, payload(session=52.0, weekly=52.0))
    refused(lane.host, cooling=3 * MINUTE)
    lane.graph.store.set_feedback(
        OTHER, "the merge conflicted in a.txt", from_person=False, source=FeedbackSource.CONFLICT
    )

    lane.scene.lane_moves()

    assert lane.runtime.requests, "the rework ran in the lane"
    assert len(lane.decisions) == len(lane.runtime.requests), "each call asked of the guard"
    assert admitted(lane.host) == [OTHER], "the admission names the unit moved"


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
