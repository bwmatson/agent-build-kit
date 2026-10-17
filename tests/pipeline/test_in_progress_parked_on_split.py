"""A planned or unplanned unit parked on a split holds no place whatever its cause field says
(spec: a-dropped-unit-parked-on-a-split-takes-no-place). Each test sets a parked unit beside the
one it is told from, so the file fails as a whole until the rule is in."""

from __future__ import annotations

from typing import Any

from agent_build_kit.pipeline.unit_store import Cause, StoredUnit
from agent_build_kit.pipeline.units import PLANNED, RUNNING, in_progress, start_room
from tests.factories import stored_unit


def entry(state: str, cause: Cause | None = None) -> dict[str, Any]:
    return {
        "state": state,
        "at": "2026-01-01T00:00:00+00:00",
        **({"cause": cause} if cause else {}),
    }


def unit(uid: str, state: str = PLANNED, *, cause: Cause | None = None, **kw: Any) -> StoredUnit:
    """A unit of its own change with a branch, whose latest history entry carries `cause`."""
    return stored_unit(
        uid,
        change=uid.split("/")[0],
        state=state,
        branch=f"spec/{uid}",
        history=(entry(state, cause),),
        **kw,
    )


def test_a_unit_parked_on_a_split_is_not_in_progress_with_or_without_a_cause() -> None:
    planned = unit("a/1", parked_splits=["acp"])
    unplanned = unit("b/1", "unplanned", parked_splits=["acp"])
    held = unit("c/1", cause=Cause.SPLIT_HELD, parked_splits=["acp"])

    assert [in_progress(u) for u in (planned, unplanned, held)] == [False, False, False]


def test_a_planned_unit_with_the_cause_split_held_is_not_counted_without_splits() -> None:
    wiped = unit("a/1", cause=Cause.SPLIT_HELD)
    parked = unit("b/1", "unplanned", parked_splits=["acp"])

    assert [in_progress(wiped), in_progress(parked)] == [False, False]


def test_an_unplanned_unit_with_work_and_no_park_counts_as_before() -> None:
    parked = unit("a/1", "unplanned", parked_splits=["acp"])
    with_pr = unit("b/1", "unplanned", pr=7)
    pushed = unit("c/1", "unplanned", pushed="abc1234")

    assert [in_progress(u) for u in (parked, with_pr, pushed)] == [False, True, True]


def test_a_park_followed_by_another_cause_counts_because_the_unit_is_on_its_way() -> None:
    parked = unit("a/1", parked_splits=["acp"])
    requeued = unit("b/1", cause=Cause.REQUEUED, parked_splits=["acp"])

    assert [in_progress(parked), in_progress(requeued)] == [False, True]


def test_a_unit_whose_parked_splits_were_cleared_counts_by_the_normal_rules() -> None:
    parked = unit("a/1", "unplanned", parked_splits=["acp"])
    cleared = unit("b/1", "unplanned", parked_splits=[], parked_sha="")

    assert [in_progress(parked), in_progress(cleared)] == [False, True]


def test_two_parked_units_leave_the_room_whole() -> None:
    counted = [stored_unit(f"run{n}/1", change=f"run{n}", state=RUNNING) for n in range(4)]
    parked = [unit("p/1", parked_splits=["acp"]), unit("q/1", "unplanned", parked_splits=["acp"])]

    assert start_room([*counted, *parked], 5) == 1
