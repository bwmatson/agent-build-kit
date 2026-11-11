"""A merge and the removal of a branch work on the direct dependents only.

Over a store whose lists are reduced, A merged moves B, which is built on it, and not C, which
is built on B: C follows B's move, so it is not moved a second time, and the probe that decides
whether A's branch can go claims B alone.
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

from agent_build_kit.pipeline import events
from agent_build_kit.pipeline.unit_store import Cause, UnitStore
from agent_build_kit.pipeline.units import HELD, IN_REVIEW, MERGED, PLANNED, SETTLING
from tests.factories import commit, git, init_repo
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
        self.restacked.append((child.id, old_base, new_base))

    def retarget(self, child, base) -> None:
        if self.refuse:
            raise RuntimeError("conflict")

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
            retarget=self.retarget,
            log=self.logged.append,
            **kwargs,
        )

    def pass_over(self, store: UnitStore) -> None:
        """The check each pass makes of a merged unit's branch."""
        events.remove_satisfied(
            store.get(A),
            store=store,
            claim=self.claim,
            remove_worktree=lambda repo, branch: self.removed.append(branch),
            delete_branch=lambda repo, branch: self.deleted.append(branch),
            on_new_base=lambda child: True,
            log=self.logged.append,
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


def test_a_merge_records_the_direct_dependent_as_owed_a_move_and_not_the_unit_built_on_it(
    store: UnitStore,
) -> None:
    calls = Calls()

    failures = calls.release(store)

    assert failures == []
    assert store.get(B).cause is Cause.BASE_CHANGED
    assert store.get(C).cause is not Cause.BASE_CHANGED


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
    store.set_state(B, IN_REVIEW, cause=Cause.RESTACK_HANDED_BACK)
    calls.claimed.clear()

    calls.pass_over(store)

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

    failures = calls.release(store, resume=told)

    assert failures == [f"{B} not moved off {OLD_BASE} — conflict"]
    assert calls.deleted == []
    assert C not in calls.claimed


def never_told(*args: object, **kwargs: object) -> bool:
    return False


def told(*args: object, **kwargs: object) -> bool:
    return True


@pytest.mark.parametrize("resume", [never_told, told], ids=["not told", "told"])
def test_a_merge_with_a_child_in_review_restacks_nothing_and_keeps_the_branch(
    store: UnitStore, resume: Any
) -> None:
    calls = Calls()

    calls.release(store, resume=resume)

    assert calls.restacked == [], "nothing is moved or handed anywhere in the poll"
    assert calls.deleted == [], "a child still owed its move keeps the branch it left"


def test_a_child_in_review_that_is_not_told_is_recorded_as_owed_its_move(store: UnitStore) -> None:
    Calls().release(store, resume=never_told)

    child = store.get(B)
    assert child.state == IN_REVIEW
    assert child.cause is Cause.BASE_CHANGED


def test_the_merged_units_branch_goes_on_the_first_pass_after_the_last_child_has_moved(
    store: UnitStore,
) -> None:
    calls = Calls()
    calls.release(store, resume=never_told)

    def pass_over() -> None:
        events.remove_satisfied(
            store.get(A),
            store=store,
            claim=calls.claim,
            remove_worktree=lambda repo, branch: calls.removed.append(branch),
            delete_branch=lambda repo, branch: calls.deleted.append(branch),
            on_new_base=lambda child: True,
            log=calls.logged.append,
        )

    pass_over()
    assert calls.deleted == [], "kept while B is owed its restack"

    store.set_state(B, IN_REVIEW, cause=Cause.RESTACK_HANDED_BACK)
    pass_over()

    assert calls.removed == [OLD_BASE]
    assert calls.deleted == [OLD_BASE]


def pass_over_merged(store: UnitStore, calls: Calls, repos: dict[str, Path]) -> None:
    """The check each poll makes of the merged units whose branch is still there."""
    events.remove_merged_branches(
        store,
        repos=repos,
        claim=calls.claim,
        remove_worktree=lambda repo, branch: calls.removed.append(branch),
        delete_branch=lambda repo, branch: calls.deleted.append(branch),
        on_new_base=lambda child: True,
        log=calls.logged.append,
    )


@pytest.fixture
def checkout(tmp_path: Path) -> Path:
    """A repository whose local branches are `main` and the merged unit's."""
    repo = init_repo(tmp_path / "app")
    commit(repo, "one.txt")
    git(repo, "branch", OLD_BASE)
    return repo


def test_a_merged_units_branch_is_removed_once_the_child_it_waited_for_has_moved(
    store: UnitStore, checkout: Path
) -> None:
    store.set_state(B, IN_REVIEW, cause=Cause.RESTACK_HANDED_BACK)
    calls = Calls()

    pass_over_merged(store, calls, {"app": checkout})

    assert calls.deleted == [OLD_BASE]
    assert calls.removed == [OLD_BASE]


def test_a_merged_units_branch_is_kept_while_a_child_is_owed_its_move(
    store: UnitStore, checkout: Path
) -> None:
    store.set_state(B, IN_REVIEW, cause=Cause.BASE_CHANGED)
    calls = Calls()

    pass_over_merged(store, calls, {"app": checkout})

    assert calls.deleted == []
    assert calls.removed == []


def test_a_merged_unit_with_no_local_branch_is_left_alone(store: UnitStore, tmp_path: Path) -> None:
    store.set_state(B, IN_REVIEW, cause=Cause.RESTACK_HANDED_BACK)
    other = init_repo(tmp_path / "other")
    commit(other, "one.txt")
    calls = Calls()

    pass_over_merged(store, calls, {"app": other})

    assert calls.deleted == [] and calls.removed == []


def test_a_unit_that_is_not_merged_or_is_in_another_repo_is_left_alone(
    store: UnitStore, checkout: Path
) -> None:
    store.set_state(B, IN_REVIEW, cause=Cause.RESTACK_HANDED_BACK)
    calls = Calls()

    pass_over_merged(store, calls, {"platform": checkout})
    assert calls.deleted == [], "its repository is not one polled"

    store.set_state(A, SETTLING)
    pass_over_merged(store, calls, {"app": checkout})
    assert calls.deleted == [], "a settling unit is not merged"
