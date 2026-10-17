"""`cause_since` dates the entry that set a cause: a carry keeps a backoff, a parking ends it."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.pipeline.unit_store import KEEP, PARK_BACKOFF, Cause, UnitStore, backoff_ends
from agent_build_kit.pipeline.units import PLANNED, RUNNING
from tests import fake_clock
from tests.factories import unit

CHANGE = "add-marker"
UNIT = "add-marker/1"
OTHER = "add-marker/2"


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> fake_clock.FakeClock:
    return fake_clock.install(monkeypatch)


@pytest.fixture
def store(tmp_path: Path, clock: fake_clock.FakeClock) -> UnitStore:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit(UNIT), unit(OTHER)])
    return store


def park(store: UnitStore) -> None:
    store.set_state(UNIT, PLANNED, cause=Cause.HOST_UNAVAILABLE)


def demote_and_promote(store: UnitStore) -> None:
    store.upsert([unit(OTHER)], change=CHANGE)
    store.upsert([unit(UNIT), unit(OTHER)], change=CHANGE)


def test_cause_since_is_when_the_cause_was_set_not_when_it_was_carried(
    store: UnitStore, clock: fake_clock.FakeClock
) -> None:
    park(store)
    parked_at = clock.now()
    clock.advance(20)

    demote_and_promote(store)

    assert store.get(UNIT).cause_since == parked_at


def test_cause_since_is_none_without_a_cause(store: UnitStore) -> None:
    assert store.get(UNIT).cause_since is None
    park(store)
    store.set_state(UNIT, RUNNING)
    assert store.get(UNIT).cause_since is None


def test_a_demotion_and_a_promotion_leave_the_backoff_where_it_was(
    store: UnitStore, clock: fake_clock.FakeClock
) -> None:
    park(store)
    before = backoff_ends(store.get(UNIT))
    clock.advance(20)

    demote_and_promote(store)

    after = backoff_ends(store.get(UNIT))
    assert before is not None
    assert after == before


def test_a_second_parking_restarts_the_backoff(
    store: UnitStore, clock: fake_clock.FakeClock
) -> None:
    park(store)
    clock.advance(20)

    park(store)

    unit_now = store.get(UNIT)
    assert unit_now.cause_since == clock.now()
    assert backoff_ends(unit_now) == clock.now() + PARK_BACKOFF[1]


def test_a_carry_is_not_a_parking_and_a_second_parking_is(store: UnitStore) -> None:
    park(store)
    assert store.get(UNIT).parked_attempts == 1

    demote_and_promote(store)
    assert store.get(UNIT).parked_attempts == 1
    assert store.get(UNIT).cause is Cause.HOST_UNAVAILABLE

    park(store)
    assert store.get(UNIT).parked_attempts == 2


def test_a_carried_host_unavailable_entry_keeps_the_step_and_the_count(
    store: UnitStore,
) -> None:
    park(store)
    store.record_step(UNIT, "push")

    store.set_state(UNIT, PLANNED, cause=KEEP)

    kept = store.get(UNIT)
    assert (kept.step, kept.parked_attempts) == ("push", 1)
    assert kept.cause is Cause.HOST_UNAVAILABLE


def test_a_demotion_and_a_promotion_keep_the_step(store: UnitStore) -> None:
    park(store)
    store.record_step(UNIT, "push")

    demote_and_promote(store)

    assert store.get(UNIT).step == "push"
