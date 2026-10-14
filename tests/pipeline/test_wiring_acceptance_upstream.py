"""A running or reviewed acceptance unit follows every earlier unit of its change.

An earlier unit that is not among the unit's stored dependencies still stops a running
acceptance unit when it goes back (`build_upstream_incomplete`) and sends one in review back
to planned while its branch is changing (`follow_predecessors`). An ordinary unit is stopped
or moved by its own parents only, not by a unit it merely follows through another.
"""

from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path

import pytest

from agent_build_kit.pipeline.unit_store import Cause, UnitStore
from agent_build_kit.pipeline.units import (
    CLOSED,
    FAILED,
    HELD,
    IN_REVIEW,
    PLANNED,
    RUNNING,
    UnitState,
)
from agent_build_kit.pipeline.wiring import build_upstream_incomplete, follow_predecessors
from tests.factories import stored_unit as unit

PUSHED = "a" * 40
MOVED = "b" * 40
EARLIER = "feature/1"
PARENT = "feature/2"
FLAGGED = "feature/3"
ORDINARY = "feature/4"


@pytest.fixture
def store(tmp_path: Path) -> UnitStore:
    return UnitStore(tmp_path / "units.json")


def plan(store: UnitStore, *, flag: str = "acceptance") -> None:
    """An independent earlier unit, a parent, a flagged unit storing only the parent, and an
    ordinary unit storing the same parent."""
    store.upsert(
        [
            unit(EARLIER, change="feature"),
            unit(PARENT, change="feature"),
            unit(FLAGGED, change="feature", depends_on=(PARENT,)),
            unit(ORDINARY, change="feature", depends_on=(PARENT,)),
        ]
    )
    store.set_calibration(FLAGGED, flag, None)


def review(store: UnitStore, uid: str, pr: int) -> None:
    store.set_state(uid, IN_REVIEW, pr=pr, branch=f"spec/{uid}")
    store.record_approval(uid, PUSHED)
    store.record_push(uid, PUSHED)


@pytest.mark.parametrize("flag", ["acceptance", "narrow"])
@pytest.mark.parametrize("state", [PLANNED, FAILED, HELD, CLOSED])
def test_a_running_flagged_unit_stops_when_an_earlier_unit_goes_back(
    store: UnitStore, flag: str, state: UnitState
) -> None:
    plan(store, flag=flag)
    review(store, PARENT, 2)
    store.set_state(EARLIER, state)
    store.set_state(FLAGGED, RUNNING)
    store.set_state(ORDINARY, RUNNING)
    upstream_incomplete = build_upstream_incomplete(store)

    reason = upstream_incomplete(store.get(FLAGGED))

    assert reason is not None
    assert reason[0] is Cause.UPSTREAM_WENT_BACK
    assert EARLIER in reason[1]
    # An ordinary unit in the same position has no parent that went back.
    assert upstream_incomplete(store.get(ORDINARY)) is None


def test_a_running_flagged_unit_stops_only_while_an_earlier_unit_is_back(store: UnitStore) -> None:
    plan(store)
    review(store, PARENT, 2)
    store.set_state(FLAGGED, RUNNING)
    upstream_incomplete = build_upstream_incomplete(store)

    assert upstream_incomplete(store.get(FLAGGED)) is not None
    review(store, EARLIER, 1)
    assert upstream_incomplete(store.get(FLAGGED)) is None


def changing(store: UnitStore, uid: str) -> dict[str, str]:
    """Send `uid` back for rework with a commit beyond its pushed head, and return the
    head reader's answer for it."""
    store.set_state(uid, PLANNED, cause=Cause.REWORK)
    store.set_state(uid, RUNNING)
    return {uid: MOVED}


def follow(store: UnitStore, heads: dict[str, str]) -> list[str]:
    return follow_predecessors(
        store,
        head=lambda stored: heads.get(stored.id, ""),
        claim=lambda stored: nullcontext(),
        log=lambda line: None,
    )


def test_a_flagged_unit_in_review_goes_back_while_an_earlier_unit_is_changing(
    store: UnitStore,
) -> None:
    plan(store)
    review(store, EARLIER, 1)
    review(store, PARENT, 2)
    review(store, FLAGGED, 3)
    review(store, ORDINARY, 4)
    heads = changing(store, EARLIER)

    moved = follow(store, heads)

    assert moved == [FLAGGED]
    stored = store.get(FLAGGED)
    assert stored.state == PLANNED
    assert stored.history[-1]["cause"] == Cause.UPSTREAM_WENT_BACK.value
    assert EARLIER in stored.history[-1]["note"]
    # The ordinary unit does not depend on the unit that is changing.
    assert store.get(ORDINARY).state == IN_REVIEW
    assert store.get(PARENT).state == IN_REVIEW


def test_an_ordinary_unit_behind_a_changing_grandparent_is_left_alone(store: UnitStore) -> None:
    """The parent's restack is deferred, so the move does not reach it, and the unit built on
    it has no parent that is changing. The flagged unit of the same pass is still moved."""
    plan(store)
    store.upsert(
        [
            unit("grand/1", change="grand"),
            unit("grand/2", change="grand", depends_on=("grand/1",)),
            unit("grand/3", change="grand", depends_on=("grand/2",)),
        ]
    )
    review(store, EARLIER, 1)
    review(store, PARENT, 2)
    review(store, FLAGGED, 3)
    review(store, "grand/1", 5)
    review(store, "grand/2", 6)
    store.set_state("grand/2", IN_REVIEW, cause=Cause.RESTACK_DEFERRED)
    review(store, "grand/3", 7)
    heads = {**changing(store, "grand/1"), **changing(store, EARLIER)}

    moved = follow(store, heads)

    assert moved == [FLAGGED]
    assert store.get("grand/3").state == IN_REVIEW
