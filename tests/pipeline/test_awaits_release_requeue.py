"""`awaits_release` reads the saved requeue of a planned unit, not its cause."""

from __future__ import annotations

from agent_build_kit.pipeline.unit_store import (
    Cause,
    RequeueReason,
    StoredUnit,
    awaits_release,
)
from agent_build_kit.pipeline.units import PLANNED
from tests.factories import stored_unit


def planned(cause: Cause, requeue: RequeueReason | None) -> StoredUnit:
    history = ({"state": PLANNED, "at": "2026-01-01T00:00:00+00:00", "cause": cause.value},)
    return stored_unit(state=PLANNED, history=history, gated_requeue=requeue)


def test_a_planned_unit_awaits_release_for_a_saved_requeue_whatever_its_cause() -> None:
    assert awaits_release(planned(Cause.BASE_CHANGED, RequeueReason.RESUME))
    assert awaits_release(planned(Cause.GATED, RequeueReason.RESTART))
    assert not awaits_release(planned(Cause.GATED, None))
    assert awaits_release(planned(Cause.SPLIT_HELD, None))
