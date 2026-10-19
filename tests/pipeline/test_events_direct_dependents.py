"""A merge and the removal of a branch work on the direct dependents only.

Over a store whose lists are reduced, A merged moves B, which is built on it, and not C, which
is built on B: C follows B's move, so it is not moved a second time, and the probe that decides
whether A's branch can go claims B alone.
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

import pytest

from agent_build_kit.pipeline import events
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import HELD, IN_REVIEW, MERGED, PLANNED
from tests.factories import stored_unit as unit

A, B, C = "feature/1", "feature/2", "feature/3"
OLD_BASE = f"spec/{A}"


class Calls:
    """What a release did: the restacks, the claims, and the branch removals."""

    def __init__(self) -> None:
        self.restacked: list[tuple[str, str, str]] = []
        self.claimed: list[str] = []
        self.removed: list[str] = []
        self.deleted: list[str] = []
        self.logged: list[str] = []
        self.refuse = False

    def restack(self, *, branch, old_base, new_base, child, parent) -> None:
        if self.refuse:
            raise RuntimeError("conflict")
        self.restacked.append((child.id, old_base, new_base))

    @contextmanager
    def claim(self, unit):
        self.claimed.append(unit.id)
        yield

    def release(self, store: UnitStore, **kwargs) -> list[str]:
        return events.release_children(
            store.get(A),
            store=store,
            restack=self.restack,
            claim=self.claim,
            remove_worktree=lambda repo, branch: self.removed.append(branch),
            delete_branch=lambda repo, branch: self.deleted.append(branch),
            retarget=lambda child, base: None,
            log=self.logged.append,
            **kwargs,
        )


@pytest.fixture
def store(tmp_path: Path) -> UnitStore:
    """A merged, B built on it, C built on B, the lists as the store keeps them."""
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
    store.set_state(A, MERGED)
    return store


def test_a_merge_moves_the_direct_dependent_and_not_the_unit_built_on_it(
    store: UnitStore,
) -> None:
    calls = Calls()

    failures = calls.release(store)

    assert failures == []
    assert calls.restacked == [(B, OLD_BASE, "main")]


def test_a_grandchild_whose_middle_unit_is_in_rework_is_not_moved_off_the_leaving_unit(
    store: UnitStore,
) -> None:
    store.set_state(B, PLANNED)
    calls = Calls()

    calls.release(store)

    assert C not in {child for child, _, _ in calls.restacked}
    assert C not in calls.claimed


def test_the_removal_of_the_branch_probes_the_direct_dependents_only(store: UnitStore) -> None:
    calls = Calls()

    calls.release(store)

    assert set(calls.claimed) == {B}
    assert calls.removed == [OLD_BASE]
    assert calls.deleted == [OLD_BASE]


def test_the_branch_is_kept_while_a_direct_dependent_is_held_for_depth(store: UnitStore) -> None:
    calls = Calls()

    calls.release(store, rebase_cap=0)

    assert store.get(B).state == HELD
    assert calls.deleted == []
    assert any(f"{B} held for depth" in line for line in calls.logged)
    assert C not in calls.claimed


def test_the_branch_is_kept_while_a_direct_dependent_is_not_moved(store: UnitStore) -> None:
    calls = Calls()
    calls.refuse = True

    failures = calls.release(store)

    assert failures == [f"{B} not moved off {OLD_BASE} — RuntimeError: conflict"]
    assert calls.deleted == []
    assert C not in calls.claimed
