"""A predecessor's reason for changing and a dependent's skip are the same after a replan."""

from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path

import pytest

from agent_build_kit.pipeline.unit_store import Cause, UnitStore
from agent_build_kit.pipeline.units import IN_REVIEW, PLANNED
from agent_build_kit.pipeline.wiring import follow_predecessors, why_branch_is_changing
from tests.factories import unit
from tests.standing_causes import REPLANS, replan

CHANGE = "feature"
PARENT = "feature/1"
CHILD = "feature/2"
REASONS = {
    Cause.UPSTREAM_WENT_BACK: "it is planned, waiting on a changing upstream",
    Cause.BASE_CHANGED: "it is planned to move onto a moved base",
}


def graph() -> list:
    return [unit(PARENT), unit(CHILD, depends_on=(PARENT,))]


@pytest.fixture
def store(tmp_path: Path) -> UnitStore:
    store = UnitStore(tmp_path / "units.json")
    store.upsert(graph(), change=CHANGE)
    return store


def reason(store: UnitStore) -> str:
    return why_branch_is_changing(store.get(PARENT), store.all(), lambda stored: "")


@pytest.mark.parametrize("how", REPLANS)
@pytest.mark.parametrize("cause", list(REASONS))
def test_a_parent_planned_for_a_cause_names_the_same_reason_after_a_replan(
    store: UnitStore, cause: Cause, how: str
) -> None:
    store.set_state(PARENT, PLANNED, cause=cause)
    assert reason(store) == REASONS[cause]

    replan(store, how, graph(), change=CHANGE)

    assert reason(store) == REASONS[cause]


@pytest.mark.parametrize("how", REPLANS)
@pytest.mark.parametrize("cause", [Cause.RESTACK_DEFERRED, Cause.RESTACK_CONFLICT])
def test_a_dependent_in_review_with_a_restack_cause_is_still_skipped_after_a_replan(
    store: UnitStore, cause: Cause, how: str
) -> None:
    store.set_state(CHILD, IN_REVIEW, pr=2, branch=f"spec/{CHILD}")
    store.set_state(CHILD, IN_REVIEW, cause=cause)
    store.set_state(PARENT, PLANNED, cause=Cause.UPSTREAM_WENT_BACK)

    replan(store, how, graph(), change=CHANGE)

    moved = follow_predecessors(
        store, head=lambda stored: "", claim=lambda stored: nullcontext(), log=lambda line: None
    )
    assert moved == []
    assert (store.get(CHILD).state, store.get(CHILD).cause) == (IN_REVIEW, cause)
