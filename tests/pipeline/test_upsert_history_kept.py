"""A replan never shortens a unit's history, and keeps a close a unit still owes."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline.unit_store import ClosePending, UnitStore
from agent_build_kit.pipeline.units import SATISFIED, Unit, UnitState
from tests.factories import unit

CHANGE = "add-marker"
IDS = {state: f"{CHANGE}/{n}" for n, state in enumerate(UnitState, start=1)}


@pytest.fixture
def store(tmp_path: Path) -> UnitStore:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit(uid) for uid in IDS.values()])
    for state, uid in IDS.items():
        store.set_state(uid, state, pr=4 if state is SATISFIED else None)
    return store


def plan(*states: UnitState) -> list[Unit]:
    return [unit(IDS[state]) for state in states]


def test_a_replan_leaves_every_history_in_place_and_the_pending_close_owed(
    store: UnitStore,
) -> None:
    store.set_close_pending(IDS[SATISFIED], ClosePending(pr=4, reason="superseded"))
    before = {uid: store.history(uid) for uid in IDS.values()}
    closed: list[tuple[str, int, str]] = []

    store.upsert(plan(UnitState.PLANNED, UnitState.MERGED, SATISFIED), change=CHANGE)
    store.upsert(plan(*UnitState), change=CHANGE)

    for uid, entries in before.items():
        after = store.history(uid)
        assert len(after) >= len(entries)
        assert after[: len(entries)] == entries
    cli.retry_closes(store, close_pr=lambda unit, pr, reason: closed.append((unit.id, pr, reason)))
    assert closed == [(IDS[SATISFIED], 4, "superseded")]
    assert store.get(IDS[SATISFIED]).close_pending is None
