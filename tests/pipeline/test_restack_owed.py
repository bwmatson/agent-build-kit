"""When a unit is owed a restack, and in which of the other cases it is not.

The graph is built through `waiting_on` only: a unit waits on a same-repo unit that is
not yet in review, never through a gate or a `merged` qualifier.
"""

from __future__ import annotations

from typing import Any

import pytest

from agent_build_kit.pipeline.restack_lane import owed_a_restack
from agent_build_kit.pipeline.unit_store import Cause, StoredUnit
from agent_build_kit.pipeline.units import (
    CLOSED,
    FAILED,
    HELD,
    IN_REVIEW,
    MERGED,
    PLANNED,
    RUNNING,
    SATISFIED,
)
from tests.factories import stored_unit
from tests.restack_lane_fakes import caused

UNIT = "feature/2"


def subject(**changes: Any) -> StoredUnit:
    fields: dict[str, Any] = {
        "state": PLANNED,
        "cause": Cause.BASE_CHANGED,
        "branch": "spec/feature/2",
        **changes,
    }
    return caused(UNIT, fields.pop("state"), fields.pop("cause"), **fields)


def owed(
    unit: StoredUnit,
    *others: StoredUnit,
    holds_base: bool = False,
    held: bool = False,
    leased: bool = False,
) -> bool:
    return owed_a_restack(
        unit,
        [unit, *others],
        holds_base=lambda unit: holds_base,
        held=lambda unit: held,
        leased=lambda unit: leased,
    )


@pytest.mark.parametrize("state", [PLANNED, RUNNING, IN_REVIEW])
@pytest.mark.parametrize("cause", [Cause.BASE_CHANGED, Cause.RESTACK_DEFERRED])
def test_a_unit_whose_base_moved_and_whose_branch_does_not_hold_it_is_owed(
    state: str, cause: Cause
) -> None:
    assert owed(subject(state=state, cause=cause))


def test_a_planned_unit_whose_prerequisite_has_merged_is_owed() -> None:
    parent = stored_unit("feature/1", change="feature", state=MERGED)

    assert owed(subject(depends_on=("feature/1",)), parent)


@pytest.mark.parametrize(
    "case",
    [
        dict(holds_base=True),
        dict(held=True),
        dict(leased=True),
    ],
    ids=["a branch that already holds its base", "a held branch lock", "a lease"],
)
def test_a_unit_that_is_owed_stops_being_so_in_each_of_these_cases(case: dict[str, bool]) -> None:
    assert owed(subject())

    assert not owed(subject(), **case)


def test_a_restack_conflict_is_not_owed_a_restack() -> None:
    assert owed(subject())

    assert not owed(subject(cause=Cause.RESTACK_CONFLICT))


@pytest.mark.parametrize("state", [FAILED, HELD, MERGED, CLOSED, SATISFIED])
def test_a_unit_that_is_failed_held_merged_closed_or_satisfied_is_not_owed(state: str) -> None:
    assert owed(subject())

    assert not owed(subject(state=state))


@pytest.mark.parametrize(
    "cause",
    [Cause.REWORK, Cause.USAGE, Cause.NEEDS_HUMAN, Cause.RELEASED, None],
)
def test_a_unit_stopped_for_another_cause_is_not_owed(cause: Cause | None) -> None:
    assert not owed(subject(cause=cause))


def test_a_planned_unit_that_waits_on_another_unit_is_not_owed_until_it_stops() -> None:
    waiting = stored_unit("feature/1", change="feature", state=PLANNED)

    assert not owed(subject(depends_on=("feature/1",)), waiting)

    reviewed = waiting.model_copy(update={"state": IN_REVIEW})
    assert owed(subject(depends_on=("feature/1",)), reviewed)
