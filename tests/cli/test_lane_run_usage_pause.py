"""A moved-base run a usage pause interrupts at the port stays the lane's: the unit is `running`,
flagged, its thread at the port; the lane retries it neither before the guard's `resume_at` nor on
a timer, and the scan after the pause resumes it at the port, asking the guard again (spec:
restack-conflicts, the port under a pause).

The scene is `tests/lane_run_usage_support.py`'s. The guard reads the faked usage endpoint and the
clock is the test's, so a retry before `resume_at` is one the test can see.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.graph.state import Node
from agent_build_kit.pipeline import spans
from agent_build_kit.pipeline.pause import PAUSE_MARKER, clear_pause
from agent_build_kit.pipeline.units import IN_REVIEW, RUNNING
from tests.lane_run_usage_support import RESOLVER_CALLS, Lane, make_lane  # noqa: F401 — fixture
from tests.restack_lane_fakes import Moving
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


def test_a_pause_at_the_port_leaves_the_unit_running_and_flagged_with_its_thread_there(
    make_lane: Callable[..., Lane],  # noqa: F811 — fixture
) -> None:
    lane = paused_at_the_port(make_lane)

    lane.scene.lane_moves()

    stops_at_the_port(lane)
    assert lane.decisions[-1].may_start is False
    assert len(lane.runtime.requests) == RESOLVER_CALLS, "the port was not called"
    assert lane.scene.offered() == [], "and no build worker is offered it"


def test_the_lane_waits_for_the_guards_resume_at_and_then_resumes_at_the_port_asking_again(
    make_lane: Callable[..., Lane],  # noqa: F811 — fixture
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = Moving()
    monkeypatch.setattr(spans, "clock", clock)
    lane = paused_at_the_port(make_lane)
    graph = lane.graph

    with cli.build_restack_lane(graph.inst, graph.store) as running:
        lane.scene.lane = running
        running.scan(graph.store.all())
        running.drain()
        stops_at_the_port(lane)
        asked = len(lane.decisions)
        resume_at = lane.decisions[-1].resume_at
        assert resume_at is not None

        # Room again and the pause lifted, but the time the guard named has not come, and no
        # timer of the lane's own retries it.
        lane.open()
        clear_pause(graph.inst.state_dir / PAUSE_MARKER)
        running.scan(graph.store.all())
        running.drain()
        assert len(lane.decisions) == asked, "retried before the guard expected to allow it"

        clock.set(resume_at + timedelta(seconds=1))
        running.scan(graph.store.all())
        running.drain()

    assert len(lane.decisions) > asked, "the guard was asked again"
    assert lane.decisions[asked].may_start
    stored = graph.store.get(OTHER)
    assert stored.state == IN_REVIEW, "the run went on from the port"
    assert stored.conflict_attempts == 1, "the resumed run is counted once, as it starts"
    assert len(lane.runtime.requests) > RESOLVER_CALLS


def test_a_runtimes_own_refusal_at_the_port_waits_for_its_time_and_resumes_at_the_port(
    make_lane: Callable[..., Lane],  # noqa: F811 — fixture
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = Moving()
    monkeypatch.setattr(spans, "clock", clock)
    resets_at = clock.now() + timedelta(minutes=20)
    lane = make_lane(refusing_from=RESOLVER_CALLS + 1, resets_at=resets_at)
    lane.open()
    graph = lane.graph

    with cli.build_restack_lane(graph.inst, graph.store) as running:
        lane.scene.lane = running
        running.scan(graph.store.all())
        running.drain()
        stops_at_the_port(lane, attempts=1)  # the port's call began
        assert lane.scene.offered() == []
        requested = len(lane.runtime.requests)

        # The runtime would answer now, and the pause marker is lifted, but its time has not
        # come: no agent is called.
        lane.runtime.refusing_from = 0
        clear_pause(graph.inst.state_dir / PAUSE_MARKER)
        running.scan(graph.store.all())
        running.drain()
        assert len(lane.runtime.requests) == requested, "retried before the runtime's time"

        clock.set(resets_at + timedelta(seconds=1))
        running.scan(graph.store.all())
        running.drain()

    assert len(lane.runtime.requests) > requested, "resumed at the port"
    assert lane.decisions[-1].may_start, "asking the guard again"
    assert graph.store.get(OTHER).state == IN_REVIEW
