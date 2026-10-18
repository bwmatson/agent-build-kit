"""A unit in review is not set back for a predecessor that builds nothing."""

from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path

import pytest

from agent_build_kit.pipeline.unit_store import Cause, StoredUnit, UnitStore
from agent_build_kit.pipeline.units import (
    IN_REVIEW,
    PLANNED,
    UnitState,
)
from agent_build_kit.pipeline.wiring import follow_predecessors, why_branch_is_changing
from tests.factories import stored_unit as unit

PUSHED = "a" * 40
MOVED = "b" * 40


@pytest.fixture
def store(tmp_path: Path) -> UnitStore:
    return UnitStore(tmp_path / "units.json")


def review(store: UnitStore, uid: str, pr: int) -> None:
    store.set_state(uid, IN_REVIEW, pr=pr, branch=f"spec/{uid}")
    store.record_approval(uid, PUSHED)
    store.record_push(uid, PUSHED)


def moved_head(_unit: StoredUnit) -> str:
    return MOVED


def run_pass(store: UnitStore) -> list[str]:
    return follow_predecessors(store, head=moved_head, claim=lambda _u: nullcontext(), log=print)


@pytest.mark.parametrize("state", [UnitState.UNPLANNED, UnitState.RETIRED])
def test_a_unit_in_review_stays_when_its_only_parent_builds_nothing(
    store: UnitStore, state: UnitState
) -> None:
    store.upsert([unit("a/1", change="a"), unit("a/2", change="a", depends_on=("a/1",))])
    store.set_state("a/1", state, branch="spec/a/1")
    store.record_push("a/1", PUSHED)
    review(store, "a/2", 2)

    assert run_pass(store) == []
    assert store.get("a/2").state == IN_REVIEW


@pytest.mark.parametrize("state", [UnitState.UNPLANNED, UnitState.RETIRED])
def test_a_dropped_branch_is_not_changing(store: UnitStore, state: UnitState) -> None:
    store.upsert([unit("a/1", change="a")])
    store.set_state("a/1", state, branch="spec/a/1")
    store.record_push("a/1", PUSHED)

    assert why_branch_is_changing(store.get("a/1"), store.all(), moved_head) == ""


def test_a_chain_whose_middle_unit_is_unplanned_moves_nothing_below_it(store: UnitStore) -> None:
    store.upsert(
        [
            unit("a/1", change="a"),
            unit("a/2", change="a", depends_on=("a/1",)),
            unit("a/3", change="a", depends_on=("a/2",)),
        ]
    )
    review(store, "a/1", 1)
    store.set_state("a/2", UnitState.UNPLANNED, branch="spec/a/2")
    store.record_push("a/2", PUSHED)
    review(store, "a/3", 3)

    assert run_pass(store) == []
    assert store.get("a/3").state == IN_REVIEW


def test_a_planned_parent_with_a_commit_beyond_pushed_still_sets_the_child_back(
    store: UnitStore,
) -> None:
    """Beside a child whose parent was dropped, which stays."""
    store.upsert(
        [
            unit("a/1", change="a"),
            unit("a/2", change="a", depends_on=("a/1",)),
            unit("a/3", change="a"),
            unit("a/4", change="a", depends_on=("a/3",)),
        ]
    )
    review(store, "a/1", 1)
    review(store, "a/2", 2)
    store.set_state("a/1", PLANNED)
    store.set_state("a/3", UnitState.UNPLANNED, branch="spec/a/3")
    store.record_push("a/3", PUSHED)
    review(store, "a/4", 4)

    assert run_pass(store) == ["a/2"]
    assert store.get("a/2").cause is Cause.UPSTREAM_WENT_BACK
    assert store.get("a/4").state == IN_REVIEW
