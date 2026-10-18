"""A state change the store makes on its own account carries a standing cause (`KEEP`)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.pipeline.unit_store import (
    EVENT_CAUSES,
    KEEP,
    STANDING_CAUSES,
    UNPLANNED,
    Cause,
    UnitStore,
)
from agent_build_kit.pipeline.units import PLANNED, RUNNING
from tests.factories import unit
from tests.standing_causes import EVENT, STANDING

UNIT = "add-marker/1"


@pytest.fixture
def store(tmp_path: Path) -> UnitStore:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit(UNIT)])
    return store


def test_standing_and_event_causes_are_disjoint_and_exactly_the_causes() -> None:
    assert STANDING_CAUSES.isdisjoint(EVENT_CAUSES)
    assert STANDING_CAUSES | EVENT_CAUSES == set(Cause)
    assert (STANDING_CAUSES, EVENT_CAUSES) == (set(STANDING), set(EVENT))


@pytest.mark.parametrize("cause", STANDING)
def test_keep_after_a_standing_cause_records_it_with_the_note_and_marks_it_carried(
    store: UnitStore, cause: Cause
) -> None:
    store.set_state(UNIT, PLANNED, note="why it stopped", cause=cause)

    store.set_state(UNIT, UNPLANNED, cause=KEEP)

    entry = store.history(UNIT)[-1]
    assert entry["cause"] == cause.value
    assert entry["note"] == "why it stopped"
    assert entry["carried"] is True
    assert store.get(UNIT).cause is cause


@pytest.mark.parametrize("cause", EVENT)
def test_keep_after_an_event_cause_records_none(store: UnitStore, cause: Cause) -> None:
    store.set_state(UNIT, PLANNED, note="done", cause=cause)

    store.set_state(UNIT, UNPLANNED, cause=KEEP)

    assert store.get(UNIT).cause is None
    assert "cause" not in store.history(UNIT)[-1]


def test_keep_with_no_cause_before_records_none(store: UnitStore) -> None:
    store.set_state(UNIT, UNPLANNED, cause=KEEP)

    assert store.get(UNIT).cause is None
    assert "cause" not in store.history(UNIT)[-1]


def test_a_note_passed_with_keep_wins(store: UnitStore) -> None:
    store.set_state(UNIT, PLANNED, note="old", cause=Cause.BASE_CHANGED)

    store.set_state(UNIT, PLANNED, note="new", cause=KEEP)

    assert store.history(UNIT)[-1]["note"] == "new"
    assert store.get(UNIT).cause is Cause.BASE_CHANGED


def test_no_cause_after_rework_still_records_none(store: UnitStore) -> None:
    store.set_state(UNIT, PLANNED, cause=Cause.REWORK)

    store.set_state(UNIT, RUNNING)

    assert store.get(UNIT).cause is None
    assert "carried" not in store.history(UNIT)[-1]
    store.set_state(UNIT, UNPLANNED, cause=KEEP)
    assert store.get(UNIT).cause is None, "nothing stood to be carried"


def test_a_history_never_shrinks_under_a_carry(store: UnitStore) -> None:
    store.set_state(UNIT, PLANNED, cause=Cause.GATED)
    before = store.history(UNIT)

    store.set_state(UNIT, UNPLANNED, cause=KEEP)
    store.set_state(UNIT, PLANNED, cause=KEEP)

    after = store.history(UNIT)
    assert len(after) == len(before) + 2
    assert after[: len(before)] == before
