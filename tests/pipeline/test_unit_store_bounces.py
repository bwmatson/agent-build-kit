"""The store counts a unit put back from `running` again and again with the same cause.

Counted where every state change is written. A run shorter than the span, the same cause
as the previous counted bounce, and a write into `planned` or `held` raise the count; a
different cause restarts it, and a long run, a missing cause, review, failure, a finished
state or a person's `abk requeue` zero it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_build_kit.pipeline.unit_store import Cause, UnitStore
from agent_build_kit.pipeline.units import (
    CLOSED,
    FAILED,
    HELD,
    IN_REVIEW,
    MERGED,
    PLANNED,
    RUNNING,
    SATISFIED,
    UnitState,
)
from tests import fake_clock
from tests.bounce_support import bounce, bounce_times
from tests.factories import stored_unit as unit

UID = "a/1"


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> fake_clock.FakeClock:
    return fake_clock.install(monkeypatch)


@pytest.fixture
def store(tmp_path: Path, clock: fake_clock.FakeClock) -> UnitStore:
    found = UnitStore(tmp_path / "units.json")
    found.upsert([unit(UID, change="a")])
    return found


def test_a_short_run_put_back_counts_once_with_its_cause_and_time(
    store: UnitStore, clock: fake_clock.FakeClock
) -> None:
    bounce(store, UID, Cause.BASE_CHANGED, clock, seconds=30)

    found = store.get(UID)
    assert (found.bounces, found.bounce_cause) == (1, Cause.BASE_CHANGED)
    assert found.bounce_at == clock.now()


def test_the_same_cause_again_raises_the_count(
    store: UnitStore, clock: fake_clock.FakeClock
) -> None:
    counts = []
    for _ in range(3):
        bounce(store, UID, Cause.UPSTREAM_WENT_BACK, clock)
        counts.append(store.get(UID).bounces)

    assert counts == [1, 2, 3]


def test_a_different_cause_restarts_at_one_so_alternating_causes_stay_there(
    store: UnitStore, clock: fake_clock.FakeClock
) -> None:
    counts = []
    for cause in (Cause.BASE_CHANGED, Cause.UPSTREAM_WENT_BACK) * 2:
        bounce(store, UID, cause, clock)
        counts.append(store.get(UID).bounces)

    assert counts == [1, 1, 1, 1]
    assert store.get(UID).bounce_cause is Cause.UPSTREAM_WENT_BACK


@pytest.mark.parametrize("seconds", [120, 600])
def test_a_run_as_long_as_the_span_gives_zero(
    store: UnitStore, clock: fake_clock.FakeClock, seconds: int
) -> None:
    bounce_times(store, UID, Cause.BASE_CHANGED, clock, 2)
    assert store.get(UID).bounces == 2

    bounce(store, UID, Cause.BASE_CHANGED, clock, seconds=seconds)

    assert store.get(UID).bounces == 0


def test_the_span_is_the_one_the_store_was_given(
    tmp_path: Path, clock: fake_clock.FakeClock
) -> None:
    store = UnitStore(tmp_path / "units.json", bounce_span_seconds=10)
    store.upsert([unit(UID, change="a")])

    bounce(store, UID, Cause.BASE_CHANGED, clock, seconds=5)
    assert store.get(UID).bounces == 1

    bounce(store, UID, Cause.BASE_CHANGED, clock, seconds=30)

    assert store.get(UID).bounces == 0


def test_a_write_with_no_cause_gives_zero(store: UnitStore, clock: fake_clock.FakeClock) -> None:
    bounce_times(store, UID, Cause.BASE_CHANGED, clock, 2)
    assert store.get(UID).bounces == 2

    bounce(store, UID, None, clock)

    assert store.get(UID).bounces == 0


def test_a_hold_counts_as_a_return_to_planned_does(
    store: UnitStore, clock: fake_clock.FakeClock
) -> None:
    bounce(store, UID, Cause.BASE_CHANGED, clock)
    bounce(store, UID, Cause.BASE_CHANGED, clock, to=HELD)

    assert store.get(UID).bounces == 2


FINISHED_OR_OUT = [
    IN_REVIEW,
    FAILED,
    MERGED,
    CLOSED,
    SATISFIED,
    UnitState.UNPLANNED,
    UnitState.RETIRED,
]


@pytest.mark.parametrize("state", FINISHED_OR_OUT)
def test_review_failure_and_the_finished_states_zero_the_count(
    store: UnitStore, clock: fake_clock.FakeClock, state: UnitState
) -> None:
    bounce_times(store, UID, Cause.BASE_CHANGED, clock, 2)
    assert store.get(UID).bounces == 2

    store.set_state(UID, state, branch=f"spec/{UID}", pr=1)

    assert store.get(UID).bounces == 0


def test_a_write_into_running_leaves_the_count(
    store: UnitStore, clock: fake_clock.FakeClock
) -> None:
    bounce_times(store, UID, Cause.BASE_CHANGED, clock, 2)

    store.set_state(UID, RUNNING, branch=f"spec/{UID}")

    assert store.get(UID).bounces == 2


def test_a_release_from_planned_leaves_the_count(
    store: UnitStore, clock: fake_clock.FakeClock
) -> None:
    bounce_times(store, UID, Cause.BASE_CHANGED, clock, 2)

    store.set_state(UID, PLANNED, cause=Cause.RELEASED)

    assert store.get(UID).bounces == 2


def test_a_persons_requeue_zeroes_the_count_and_an_automatic_one_does_not(
    store: UnitStore, clock: fake_clock.FakeClock
) -> None:
    bounce_times(store, UID, Cause.REQUEUED, clock, 2)
    bounce(store, UID, Cause.REQUEUED, clock)
    assert store.get(UID).bounces == 3

    store.set_state(UID, RUNNING, branch=f"spec/{UID}")
    clock.advance(30)
    store.set_state(UID, PLANNED, cause=Cause.REQUEUED, by="abk requeue")

    assert store.get(UID).bounces == 0


def test_three_quick_parks_for_the_host_reach_three(
    store: UnitStore, clock: fake_clock.FakeClock
) -> None:
    bounce_times(store, UID, Cause.HOST_UNAVAILABLE, clock, 3, seconds=20)

    assert store.get(UID).bounces == 3


def test_a_replan_keeps_the_count_the_cause_and_the_time(
    store: UnitStore, clock: fake_clock.FakeClock
) -> None:
    bounce_times(store, UID, Cause.BASE_CHANGED, clock, 2)
    before = store.get(UID)

    store.upsert([unit(UID, change="a", title="Reworded")])

    after = store.get(UID)
    assert (after.bounces, after.bounce_cause, after.bounce_at) == (
        2,
        Cause.BASE_CHANGED,
        before.bounce_at,
    )


def test_an_older_store_file_loads_with_zero_and_counts_from_there(
    store: UnitStore, clock: fake_clock.FakeClock
) -> None:
    bounce_times(store, UID, Cause.BASE_CHANGED, clock, 2)

    def without(node: object) -> object:
        if isinstance(node, dict):
            return {
                k: without(v)
                for k, v in node.items()
                if k not in ("bounces", "bounce_cause", "bounce_at")
            }
        if isinstance(node, list):
            return [without(v) for v in node]
        return node

    store.path.write_text(json.dumps(without(json.loads(store.path.read_text()))))
    assert store.get(UID).bounces == 0

    bounce(store, UID, Cause.BASE_CHANGED, clock)

    assert store.get(UID).bounces == 1


def test_a_unit_that_never_bounced_is_stored_without_the_bounce_keys(store: UnitStore) -> None:
    store.set_state(UID, RUNNING, branch=f"spec/{UID}")

    assert "bounce" not in store.path.read_text()
