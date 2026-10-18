"""A same-repo parent that builds nothing does not hold its child at a step boundary.

`build_upstream_incomplete` reads a stored dependency the way the scheduler's `waiting_on`
does: a parent in `BUILDS_NOTHING` (unplanned or retired) is skipped, and one still to be
built holds the child.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.pipeline.unit_store import Cause, UnitStore
from agent_build_kit.pipeline.units import (
    BUILDS_NOTHING,
    CLOSED,
    FAILED,
    HELD,
    IN_REVIEW,
    MERGED,
    PLANNED,
    RUNNING,
    SATISFIED,
    UnitState,
    waiting_on,
)
from agent_build_kit.pipeline.wiring import build_upstream_incomplete
from tests.factories import stored_unit as unit


@pytest.fixture
def store(tmp_path: Path) -> UnitStore:
    return UnitStore(tmp_path / "units.json")


def two_units(store: UnitStore, parent_state: UnitState) -> None:
    store.upsert([unit("a/1", change="a"), unit("a/2", change="a", depends_on=("a/1",))])
    store.set_state("a/1", parent_state)
    store.set_state("a/2", RUNNING)


@pytest.mark.parametrize("state", [UnitState.UNPLANNED, UnitState.RETIRED])
def test_a_parent_that_builds_nothing_does_not_stop_its_child(
    store: UnitStore, state: UnitState
) -> None:
    two_units(store, state)

    assert build_upstream_incomplete(store)(store.get("a/2")) is None


def test_only_a_parent_that_builds_nothing_or_is_reviewed_leaves_its_child_going(
    tmp_path: Path,
) -> None:
    held = {}
    for state in (
        *BUILDS_NOTHING,
        PLANNED,
        RUNNING,
        FAILED,
        HELD,
        CLOSED,
        IN_REVIEW,
        MERGED,
        SATISFIED,
    ):
        store = UnitStore(tmp_path / f"{state}.json")
        two_units(store, state)
        found = build_upstream_incomplete(store)(store.get("a/2"))
        if found is not None:
            assert found[0] is Cause.UPSTREAM_WENT_BACK
            assert "a/1" in found[1]
        held[state] = found is not None

    assert {state for state, stops in held.items() if stops} == {
        PLANNED,
        RUNNING,
        FAILED,
        HELD,
        CLOSED,
    }


@pytest.mark.parametrize("state", BUILDS_NOTHING)
def test_a_unit_the_scheduler_admits_is_not_stopped_by_the_guard(
    store: UnitStore, state: UnitState
) -> None:
    two_units(store, state)
    child = store.get("a/2")

    assert waiting_on(child, store.all()) == []
    assert build_upstream_incomplete(store)(child) is None


@pytest.mark.parametrize("state", [UnitState.UNPLANNED, UnitState.RETIRED])
def test_a_cross_repo_parent_that_builds_nothing_changes_nothing(
    store: UnitStore, state: UnitState
) -> None:
    """A cross-repo parent never held the child; the same-repo one beside it is what is read."""
    store.upsert(
        [
            unit("a/1", change="a", repo="platform"),
            unit("a/3", change="a"),
            unit("a/2", change="a", repo="app", depends_on=("a/1", "a/3")),
        ]
    )
    store.set_state("a/1", state)
    store.set_state("a/3", state)
    store.set_state("a/2", RUNNING)

    assert build_upstream_incomplete(store)(store.get("a/2")) is None


@pytest.mark.parametrize("dropped", [UnitState.UNPLANNED, UnitState.RETIRED])
def test_a_child_with_two_parents_is_held_naming_the_planned_one_only(
    store: UnitStore, dropped: UnitState
) -> None:
    store.upsert(
        [
            unit("a/1", change="a"),
            unit("a/2", change="a"),
            unit("a/3", change="a", depends_on=("a/1", "a/2")),
        ]
    )
    store.set_state("a/1", dropped)
    store.set_state("a/2", PLANNED)
    store.set_state("a/3", RUNNING)

    found = build_upstream_incomplete(store)(store.get("a/3"))

    assert found is not None
    assert "a/2" in found[1]
    assert "a/1" not in found[1]
