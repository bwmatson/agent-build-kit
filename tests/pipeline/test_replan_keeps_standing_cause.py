"""A replan, a vanished change and a join leave a unit's standing cause as it was."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.pipeline.unit_store import STANDING_CAUSES, Cause, UnitStore
from agent_build_kit.pipeline.units import PLANNED, Join, UnitState
from tests.factories import unit

CHANGE = "add-marker"
UNIT = "add-marker/1"
OTHER = "add-marker/2"
CARRIED = [
    Cause.SPLIT_HELD,
    Cause.GATED,
    Cause.BASE_CHANGED,
    Cause.RESTACK_DEFERRED,
    Cause.UPSTREAM_WENT_BACK,
    Cause.HOST_UNAVAILABLE,
]


@pytest.fixture
def store(tmp_path: Path) -> UnitStore:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit(UNIT), unit(OTHER)])
    return store


def stop(store: UnitStore, cause: Cause | None, *, uid: str = UNIT) -> None:
    store.set_state(uid, PLANNED, note="why it stopped", cause=cause)


def test_the_carried_causes_are_standing_ones() -> None:
    assert set(CARRIED) <= STANDING_CAUSES


@pytest.mark.parametrize("cause", CARRIED)
def test_a_replan_that_omits_a_unit_and_one_that_includes_it_keep_its_cause(
    store: UnitStore, cause: Cause
) -> None:
    stop(store, cause)
    before = store.history(UNIT)

    store.upsert([unit(OTHER)], change=CHANGE)

    omitted = store.get(UNIT)
    assert omitted.state == UnitState.UNPLANNED
    assert omitted.cause is cause

    store.upsert([unit(UNIT), unit(OTHER)], change=CHANGE)

    back = store.get(UNIT)
    assert (back.state, back.cause) == (PLANNED, cause)
    history = store.history(UNIT)
    assert len(history) == len(before) + 2
    assert [entry.get("carried") for entry in history[-2:]] == [True, True]
    assert [entry.get("cause") for entry in history[-2:]] == [cause.value] * 2
    assert all(entry.get("note") == "why it stopped" for entry in history[-2:])


@pytest.mark.parametrize("cause", [None, Cause.REQUEUED])
def test_a_unit_without_a_standing_cause_reads_none_beside_one_that_has_it(
    store: UnitStore, cause: Cause | None
) -> None:
    store.upsert([unit(UNIT), unit(OTHER)])
    stop(store, cause)
    stop(store, Cause.BASE_CHANGED, uid=OTHER)

    store.upsert([], change=CHANGE)
    store.upsert([unit(UNIT), unit(OTHER)], change=CHANGE)

    assert store.get(UNIT).cause is None
    assert not any(entry.get("carried") for entry in store.history(UNIT))
    assert store.get(OTHER).cause is Cause.BASE_CHANGED


@pytest.mark.parametrize("cause", CARRIED)
def test_a_vanished_change_keeps_a_standing_cause(store: UnitStore, cause: Cause) -> None:
    stop(store, cause)

    assert store.unplan_vanished(["other-change"]) == [UNIT, OTHER]

    gone = store.get(UNIT)
    assert gone.state == UnitState.UNPLANNED
    assert gone.cause is cause
    assert store.history(UNIT)[-1]["carried"] is True


@pytest.mark.parametrize("cause", CARRIED)
def test_a_join_onto_an_unstarted_unit_keeps_a_standing_cause_and_notes_the_join(
    store: UnitStore, cause: Cause
) -> None:
    stop(store, cause)

    assert store.join(Join(onto=UNIT, unit=OTHER), group_kinds=()) is not None

    entry = store.history(UNIT)[-1]
    assert store.get(UNIT).cause is cause
    assert entry["note"] == "joined"
    assert entry["carried"] is True
