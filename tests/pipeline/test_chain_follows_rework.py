"""Units behind a unit sent back follow the chain over reduced lists.

A, B and C are a chain stored as `B on A` and `C on B`; a `Needs:` that names A for C adds
nothing the store keeps. A going back moves B because B's parent is changing, and C because
B's branch is then changing, in one pass, with no wait of C on A.
"""

from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path

import pytest

from agent_build_kit.pipeline.unit_store import Cause, UnitStore
from agent_build_kit.pipeline.units import CLOSED, IN_REVIEW, PLANNED, RUNNING, waiting_on
from agent_build_kit.pipeline.wiring import build_upstream_incomplete, follow_predecessors
from tests.factories import stored_unit as unit

PUSHED = "a" * 40
MOVED = "b" * 40
A, B, C = "feature/1", "feature/2", "feature/3"


@pytest.fixture
def store(tmp_path: Path) -> UnitStore:
    """The chain with B and C in review; C's plan names both of its ancestors."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert(
        [
            unit(A, change="feature"),
            unit(B, change="feature", depends_on=(A,)),
            unit(C, change="feature", depends_on=(A, B)),
        ]
    )
    for n, uid in enumerate((A, B, C), start=1):
        store.set_state(uid, IN_REVIEW, pr=n, branch=f"spec/{uid}")
        store.record_approval(uid, PUSHED)
        store.record_push(uid, PUSHED)
    return store


def send_back(store: UnitStore) -> dict[str, str]:
    """A is sent back for rework with a commit beyond its pushed head."""
    store.set_state(A, PLANNED, cause=Cause.REWORK)
    store.set_state(A, RUNNING)
    return {A: MOVED}


def follow(store: UnitStore, heads: dict[str, str], deliver=None) -> list[str]:
    return follow_predecessors(
        store,
        head=lambda stored: heads.get(stored.id, ""),
        claim=lambda stored: nullcontext(),
        deliver=deliver,
        log=lambda line: None,
    )


def test_the_store_holds_the_chain_reduced(store: UnitStore) -> None:
    assert store.get(C).depends_on == (B,)


def test_a_grandparent_sent_back_moves_the_parent_and_the_unit_follows_it(
    store: UnitStore,
) -> None:
    heads = send_back(store)

    moved = follow(store, heads)

    assert moved == [B, C]
    assert store.get(B).state == PLANNED
    assert store.get(C).state == PLANNED
    assert store.get(C).history[-1]["cause"] == Cause.UPSTREAM_WENT_BACK.value
    assert B in store.get(C).history[-1]["note"]
    assert A not in {parent.id for parent in waiting_on(store.get(C), store.all())}


def test_a_grandparent_closed_does_not_hold_the_unit(store: UnitStore) -> None:
    store.set_state(A, CLOSED)
    store.set_state(C, RUNNING)

    assert build_upstream_incomplete(store)(store.get(C)) is None
    assert A not in {parent.id for parent in waiting_on(store.get(C), store.all())}


def test_a_restack_deferred_for_the_parent_leaves_the_unit_where_it_is(store: UnitStore) -> None:
    heads = send_back(store)
    store.set_state(B, IN_REVIEW, cause=Cause.RESTACK_DEFERRED)

    moved = follow(store, heads)

    assert moved == []
    assert store.get(B).state == IN_REVIEW
    assert store.get(C).state == IN_REVIEW


def test_a_thread_that_declines_the_move_leaves_its_unit_in_review(store: UnitStore) -> None:
    heads = send_back(store)

    moved = follow(store, heads, deliver=lambda stored, note: True)

    assert moved == [B]
    assert store.get(B).state == IN_REVIEW
    assert store.get(C).state == IN_REVIEW
