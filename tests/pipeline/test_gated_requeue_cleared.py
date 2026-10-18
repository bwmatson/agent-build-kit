"""A saved requeue is cleared in the write that records any cause other than `gated`."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.pipeline.unit_store import KEEP, Cause, RequeueReason, UnitStore
from agent_build_kit.pipeline.units import PLANNED
from tests.factories import unit
from tests.standing_causes import EVENT, STANDING

UNIT = "add-marker/1"
OTHER_CAUSES = [cause for cause in [*STANDING, *EVENT, None] if cause is not Cause.GATED]


@pytest.fixture
def store(tmp_path: Path) -> UnitStore:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit(UNIT)])
    return store


@pytest.mark.parametrize("cause", OTHER_CAUSES)
def test_a_gate_keeps_its_requeue_until_a_state_change_with_another_cause(
    store: UnitStore, cause: Cause | None
) -> None:
    store.set_state(UNIT, PLANNED, cause=Cause.GATED)
    store.set_gated_requeue(UNIT, RequeueReason.RESUME)
    assert store.get(UNIT).gated_requeue is RequeueReason.RESUME, "set right after the gate"

    store.set_state(UNIT, PLANNED, cause=Cause.GATED)
    assert store.get(UNIT).gated_requeue is RequeueReason.RESUME, "a second gated write keeps it"
    store.set_state(UNIT, PLANNED, cause=KEEP)
    assert store.get(UNIT).gated_requeue is RequeueReason.RESUME, "a carried gate keeps it"

    store.set_state(UNIT, PLANNED, cause=cause)

    assert store.get(UNIT).gated_requeue is None
