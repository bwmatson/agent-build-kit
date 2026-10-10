"""A unit in review follows its predecessor while the predecessor's branch is changing.

A predecessor's branch is changing when it is not in review, merged or satisfied
and it holds a commit beyond its last pushed head, is rebasing, or is itself
waiting on an upstream that is changing. The dependent goes back to `planned`
with the cause `upstream_went_back`, keeping its approval, branch and pull
request, and is released when the predecessor is back in review.

The branch head is read through an injected reader, so most of these tests need
no repository; the release at the end runs the real restack on a real one.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager, nullcontext
from pathlib import Path

import pytest

from agent_build_kit.pipeline.stack_runner import Restacked
from agent_build_kit.pipeline.unit_store import Cause, FeedbackSource, StoredUnit, UnitStore
from agent_build_kit.pipeline.units import (
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
from agent_build_kit.pipeline.wiring import build_restack_onto, follow_predecessors
from agent_build_kit.pipeline.workspaces import BranchBusy
from tests.factories import git, init_repo
from tests.factories import stored_unit as unit

PUSHED = "a" * 40
MOVED = "b" * 40
APPROVED = "c" * 40
PARENT = "feature/1"
CHILD = "feature/2"
GRANDCHILD = "feature/3"


class Heads:
    """The branch heads a head reader returns, by unit id; a unit not named has
    none."""

    def __init__(self) -> None:
        self.by_unit: dict[str, str] = {}

    def __call__(self, stored: StoredUnit) -> str:
        return self.by_unit.get(stored.id, "")


@pytest.fixture
def store(tmp_path: Path) -> UnitStore:
    return UnitStore(tmp_path / "units.json")


@pytest.fixture
def heads() -> Heads:
    return Heads()


@pytest.fixture
def logged() -> list[str]:
    return []


def stack(store: UnitStore, uid: str, *depends_on: str, **extra) -> None:
    store.upsert([unit(uid, depends_on=depends_on, **extra)])


def in_review(store: UnitStore, uid: str, *, pr: int, pushed: str = PUSHED) -> None:
    """Approved, pushed and waiting, as a unit in review is."""
    store.set_state(uid, IN_REVIEW, pr=pr, branch=f"spec/{uid}")
    store.record_approval(uid, APPROVED)
    store.record_push(uid, pushed)


def sent_back(store: UnitStore, uid: str, cause: Cause, source: FeedbackSource) -> None:
    store.set_state(uid, PLANNED, cause=cause)
    if source is not FeedbackSource.NONE:
        store.set_feedback(uid, "words", source=source)
    store.set_state(uid, RUNNING)


def follow(
    store: UnitStore,
    heads: Heads,
    logged: list[str],
    *,
    claim: Callable[[StoredUnit], AbstractContextManager[object]] = lambda stored: nullcontext(),
    deliver: Callable[[StoredUnit, str], bool] | None = None,
) -> list[str]:
    return follow_predecessors(store, head=heads, claim=claim, deliver=deliver, log=logged.append)


@pytest.fixture
def reworked_parent(store: UnitStore, heads: Heads) -> StoredUnit:
    """A parent sent back for review feedback and running again, pushed at
    `PUSHED`, with a dependent in review on it."""
    stack(store, PARENT)
    in_review(store, PARENT, pr=1)
    sent_back(store, PARENT, Cause.REWORK, FeedbackSource.REVIEW)
    stack(store, CHILD, PARENT)
    in_review(store, CHILD, pr=2)
    heads.by_unit[PARENT] = PUSHED
    return store.get(PARENT)


# --- 2.1 a predecessor whose branch is changing moves the dependent -------------


def test_a_predecessor_with_a_commit_beyond_its_pushed_head_sends_the_dependent_back(
    store: UnitStore, heads: Heads, logged: list[str], reworked_parent: StoredUnit
) -> None:
    heads.by_unit[PARENT] = MOVED

    follow(store, heads, logged)

    child = store.get(CHILD)
    assert child.state == PLANNED
    assert child.history[-1]["cause"] == Cause.UPSTREAM_WENT_BACK.value
    assert PARENT in child.history[-1]["note"]
    assert any(PARENT in line and CHILD in line for line in logged)


def test_the_dependent_keeps_its_approval_branch_and_pull_request(
    store: UnitStore, heads: Heads, logged: list[str], reworked_parent: StoredUnit
) -> None:
    heads.by_unit[PARENT] = MOVED

    follow(store, heads, logged)

    child = store.get(CHILD)
    assert (child.approved, child.pushed) == (APPROVED, PUSHED)
    assert (child.branch, child.pr) == (f"spec/{CHILD}", 2)


def test_the_pass_returns_the_units_it_moved(
    store: UnitStore, heads: Heads, logged: list[str], reworked_parent: StoredUnit
) -> None:
    heads.by_unit[PARENT] = MOVED

    assert follow(store, heads, logged) == [CHILD]
    assert follow(store, heads, logged) == []


def test_a_move_is_handed_to_the_delivery_and_the_pass_does_not_write_the_store(
    store: UnitStore, heads: Heads, logged: list[str], reworked_parent: StoredUnit
) -> None:
    heads.by_unit[PARENT] = MOVED
    delivered: list[tuple[str, str]] = []

    def deliver(stored: StoredUnit, note: str) -> bool:
        delivered.append((stored.id, note))
        return True

    moved = follow(store, heads, logged, deliver=deliver)

    assert moved == [CHILD]
    ((uid, note),) = delivered
    assert uid == CHILD
    assert PARENT in note
    assert store.get(CHILD).state == IN_REVIEW, "the thread's handler writes the move, not the pass"


def test_a_unit_with_nothing_to_deliver_to_is_set_back_in_the_store(
    store: UnitStore, heads: Heads, logged: list[str], reworked_parent: StoredUnit
) -> None:
    heads.by_unit[PARENT] = MOVED

    moved = follow(store, heads, logged, deliver=lambda stored, note: False)

    assert moved == [CHILD]
    child = store.get(CHILD)
    assert child.state == PLANNED
    assert child.history[-1]["cause"] == Cause.UPSTREAM_WENT_BACK.value


def test_a_predecessor_that_is_rebasing_sends_the_dependent_back_before_a_new_head_exists(
    store: UnitStore, heads: Heads, logged: list[str]
) -> None:
    stack(store, PARENT)
    in_review(store, PARENT, pr=1)
    sent_back(store, PARENT, Cause.BASE_CHANGED, FeedbackSource.NONE)
    stack(store, CHILD, PARENT)
    in_review(store, CHILD, pr=2)
    heads.by_unit[PARENT] = PUSHED

    follow(store, heads, logged)

    assert store.get(CHILD).state == PLANNED
    assert store.get(CHILD).history[-1]["cause"] == Cause.UPSTREAM_WENT_BACK.value


def test_a_predecessor_resolving_a_conflict_sends_the_dependent_back(
    store: UnitStore, heads: Heads, logged: list[str]
) -> None:
    stack(store, PARENT)
    in_review(store, PARENT, pr=1)
    sent_back(store, PARENT, Cause.REWORK, FeedbackSource.CONFLICT)
    stack(store, CHILD, PARENT)
    in_review(store, CHILD, pr=2)
    heads.by_unit[PARENT] = PUSHED

    follow(store, heads, logged)

    assert store.get(CHILD).state == PLANNED


@pytest.mark.parametrize("state", [FAILED, HELD])
def test_a_failed_or_held_predecessor_with_a_commit_beyond_its_pushed_head_sends_the_dependent_back(
    store: UnitStore, heads: Heads, logged: list[str], reworked_parent: StoredUnit, state: UnitState
) -> None:
    store.set_state(PARENT, state)
    heads.by_unit[PARENT] = MOVED

    follow(store, heads, logged)

    assert store.get(CHILD).state == PLANNED


# --- 2.2 a branch that is not changing leaves the dependent alone ---------------


def test_a_predecessor_reworking_with_its_head_unchanged_leaves_the_dependent(
    store: UnitStore, heads: Heads, logged: list[str], reworked_parent: StoredUnit
) -> None:
    assert follow(store, heads, logged) == []

    assert store.get(CHILD).state == IN_REVIEW
    assert logged == []


@pytest.mark.parametrize("state", [FAILED, HELD])
def test_a_failed_or_held_predecessor_with_its_head_unchanged_leaves_the_dependent(
    store: UnitStore, heads: Heads, logged: list[str], reworked_parent: StoredUnit, state: UnitState
) -> None:
    store.set_state(PARENT, state)

    follow(store, heads, logged)

    assert store.get(CHILD).state == IN_REVIEW


def test_a_predecessor_in_review_leaves_the_dependent_even_with_a_new_head(
    store: UnitStore, heads: Heads, logged: list[str]
) -> None:
    stack(store, PARENT)
    in_review(store, PARENT, pr=1)
    stack(store, CHILD, PARENT)
    in_review(store, CHILD, pr=2)
    heads.by_unit[PARENT] = MOVED

    follow(store, heads, logged)

    assert store.get(CHILD).state == IN_REVIEW


# --- 2.3 chains, merged and cross-repo predecessors, deferrals, busy branches ----


def test_a_chain_of_dependents_moves_in_one_pass(
    store: UnitStore, heads: Heads, logged: list[str], reworked_parent: StoredUnit
) -> None:
    stack(store, GRANDCHILD, CHILD)
    in_review(store, GRANDCHILD, pr=3)
    heads.by_unit[PARENT] = MOVED

    assert sorted(follow(store, heads, logged)) == [CHILD, GRANDCHILD]

    assert store.get(CHILD).state == PLANNED
    assert store.get(GRANDCHILD).state == PLANNED
    assert any(CHILD in line and GRANDCHILD in line for line in logged)


def test_a_chain_listed_dependent_first_still_moves_in_one_pass(
    store: UnitStore, heads: Heads, logged: list[str]
) -> None:
    stack(store, GRANDCHILD, CHILD)
    stack(store, CHILD, PARENT)
    stack(store, PARENT)
    in_review(store, PARENT, pr=1)
    sent_back(store, PARENT, Cause.REWORK, FeedbackSource.REVIEW)
    in_review(store, CHILD, pr=2)
    in_review(store, GRANDCHILD, pr=3)
    heads.by_unit[PARENT] = MOVED

    follow(store, heads, logged)

    assert store.get(GRANDCHILD).state == PLANNED


def test_the_log_names_each_unit_and_predecessor_once(
    store: UnitStore, heads: Heads, logged: list[str], reworked_parent: StoredUnit
) -> None:
    heads.by_unit[PARENT] = MOVED

    follow(store, heads, logged)
    follow(store, heads, logged)
    follow(store, heads, logged)

    assert len([line for line in logged if CHILD in line and PARENT in line]) == 1


@pytest.mark.parametrize("state", [MERGED, SATISFIED])
def test_a_merged_or_satisfied_predecessor_does_not_move_the_dependent(
    store: UnitStore, heads: Heads, logged: list[str], state: UnitState
) -> None:
    stack(store, PARENT)
    in_review(store, PARENT, pr=1)
    store.set_state(PARENT, state)
    stack(store, CHILD, PARENT)
    in_review(store, CHILD, pr=2)
    heads.by_unit[PARENT] = MOVED

    assert follow(store, heads, logged) == []

    assert store.get(CHILD).state == IN_REVIEW


def test_a_predecessor_in_another_repo_does_not_move_the_dependent(
    store: UnitStore, heads: Heads, logged: list[str]
) -> None:
    stack(store, PARENT, repo="platform")
    in_review(store, PARENT, pr=1)
    sent_back(store, PARENT, Cause.REWORK, FeedbackSource.REVIEW)
    stack(store, CHILD, PARENT)
    in_review(store, CHILD, pr=2)
    heads.by_unit[PARENT] = MOVED

    assert follow(store, heads, logged) == []

    assert store.get(CHILD).state == IN_REVIEW


def test_a_predecessor_waiting_on_a_changing_upstream_moves_its_dependent(
    store: UnitStore, heads: Heads, logged: list[str]
) -> None:
    """The grandparent changes; the parent is already planned for it, and the
    grandchild that was left in review follows the parent."""
    stack(store, PARENT)
    in_review(store, PARENT, pr=1)
    sent_back(store, PARENT, Cause.REWORK, FeedbackSource.REVIEW)
    stack(store, CHILD, PARENT)
    in_review(store, CHILD, pr=2)
    store.set_state(CHILD, PLANNED, cause=Cause.UPSTREAM_WENT_BACK, note=f"{PARENT} went back")
    stack(store, GRANDCHILD, CHILD)
    in_review(store, GRANDCHILD, pr=3)
    heads.by_unit[PARENT] = PUSHED

    follow(store, heads, logged)

    assert store.get(GRANDCHILD).state == PLANNED


def test_a_predecessor_planned_for_a_moved_base_moves_its_dependent(
    store: UnitStore, heads: Heads, logged: list[str]
) -> None:
    stack(store, PARENT)
    in_review(store, PARENT, pr=1)
    store.set_state(PARENT, PLANNED, cause=Cause.BASE_CHANGED)
    stack(store, CHILD, PARENT)
    in_review(store, CHILD, pr=2)
    heads.by_unit[PARENT] = PUSHED

    follow(store, heads, logged)

    assert store.get(CHILD).state == PLANNED


@pytest.mark.parametrize("cause", [Cause.RESTACK_DEFERRED, Cause.RESTACK_CONFLICT])
def test_a_dependent_with_a_deferred_restack_is_left_alone(
    store: UnitStore, heads: Heads, logged: list[str], reworked_parent: StoredUnit, cause: Cause
) -> None:
    store.set_state(CHILD, IN_REVIEW, cause=cause, note="restack could not finish")
    heads.by_unit[PARENT] = MOVED

    follow(store, heads, logged)

    assert store.get(CHILD).state == IN_REVIEW


def test_a_unit_held_on_a_base_is_left_alone(
    store: UnitStore, heads: Heads, logged: list[str], reworked_parent: StoredUnit
) -> None:
    store.set_state(CHILD, HELD, cause=Cause.DEPTH, held_base=f"spec/{PARENT}")
    heads.by_unit[PARENT] = MOVED

    assert follow(store, heads, logged) == []

    assert store.get(CHILD).state == HELD


def test_a_dependent_whose_branch_is_busy_is_left_for_the_next_pass_without_an_error(
    store: UnitStore, heads: Heads, logged: list[str], reworked_parent: StoredUnit
) -> None:
    heads.by_unit[PARENT] = MOVED
    busy = True

    def claim(stored: StoredUnit) -> AbstractContextManager[object]:
        if busy:
            raise BranchBusy(f"spec/{stored.id} is held")
        return nullcontext()

    assert follow(store, heads, logged, claim=claim) == []
    assert store.get(CHILD).state == IN_REVIEW

    busy = False
    assert follow(store, heads, logged, claim=claim) == [CHILD]
    assert store.get(CHILD).state == PLANNED


def test_a_dependent_that_started_building_before_the_claim_is_not_moved(
    store: UnitStore, heads: Heads, logged: list[str], reworked_parent: StoredUnit
) -> None:
    """Read again under the claim: a build that took the unit meanwhile is not
    overwritten with `planned`."""
    heads.by_unit[PARENT] = MOVED

    def claim(stored: StoredUnit) -> AbstractContextManager[object]:
        store.set_state(stored.id, RUNNING)
        return nullcontext()

    assert follow(store, heads, logged, claim=claim) == []

    assert store.get(CHILD).state == RUNNING


# --- 2.4 the dependent is released when the predecessor is back -----------------


class Stack:
    """A parent and a child branch in a real repository, with the child in review
    on the parent's pushed head, approved."""

    def __init__(self, tmp_path: Path, store: UnitStore) -> None:
        self.store = store
        self.repo = init_repo(tmp_path / "app")
        self.commit("base.txt")
        git(self.repo, "checkout", "-q", "-b", f"spec/{PARENT}")
        self.commit("one.txt")
        self.old_parent = self.sha(f"spec/{PARENT}")
        git(self.repo, "checkout", "-q", "-b", f"spec/{CHILD}")
        self.commit("two.txt")
        git(self.repo, "checkout", "-q", "main")
        stack(store, PARENT)
        in_review(store, PARENT, pr=1, pushed=self.old_parent)
        stack(store, CHILD, PARENT)
        self.old_child = self.sha(f"spec/{CHILD}")
        store.set_state(CHILD, IN_REVIEW, pr=2, branch=f"spec/{CHILD}")
        store.record_approval(CHILD, self.old_child)
        store.record_push(CHILD, self.old_child)
        self.tree = tmp_path / "child-tree"
        git(self.repo, "worktree", "add", "-q", str(self.tree), f"spec/{CHILD}")
        self.restacked = build_restack_onto(store, repo=None)

    def commit(self, name: str) -> None:
        (self.repo / name).write_text(name)
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-qm", f"add {name}")

    def sha(self, ref: str) -> str:
        return git(self.repo, "rev-parse", ref)

    def heads(self) -> Heads:
        reader = Heads()
        reader.by_unit = {PARENT: self.sha(f"spec/{PARENT}")}
        return reader

    def rework_parent(self) -> None:
        """The parent goes back for rework and commits to its branch."""
        sent_back(self.store, PARENT, Cause.REWORK, FeedbackSource.REVIEW)
        git(self.repo, "checkout", "-q", f"spec/{PARENT}")
        self.commit("rework.txt")
        git(self.repo, "checkout", "-q", "main")

    def parent_returns(self) -> None:
        self.store.set_state(PARENT, IN_REVIEW)
        self.store.record_push(PARENT, self.sha(f"spec/{PARENT}"))

    def restack_child(self) -> Restacked | None:
        """What the build's `prepare` does for a released dependent: the old base
        is worked out from the store and the tree, not given."""
        return self.restacked(
            tree=self.tree,
            branch=f"spec/{CHILD}",
            base=f"spec/{PARENT}",
            unit=self.store.get(CHILD),
        )


@pytest.fixture
def real(tmp_path: Path, store: UnitStore) -> Stack:
    return Stack(tmp_path, store)


def test_a_dependent_stays_set_back_while_the_predecessor_works_and_is_released_when_it_returns(
    store: UnitStore, logged: list[str], real: Stack
) -> None:
    real.rework_parent()
    follow(store, real.heads(), logged)
    graph = store.all()
    assert store.get(CHILD).state == PLANNED
    assert [parent.id for parent in waiting_on(store.get(CHILD), graph)] == [PARENT]

    real.parent_returns()

    assert waiting_on(store.get(CHILD), store.all()) == []


def test_the_released_dependent_restacks_onto_the_new_head_and_keeps_its_approval(
    store: UnitStore, logged: list[str], real: Stack
) -> None:
    real.rework_parent()
    follow(store, real.heads(), logged)
    real.parent_returns()

    restacked = real.restack_child()

    assert restacked is not None
    assert restacked.conflict == ""
    child = store.get(CHILD)
    new_parent = real.sha(f"spec/{PARENT}")
    assert child.approved == real.sha(f"spec/{CHILD}") != real.old_child
    assert git(real.repo, "merge-base", "--is-ancestor", new_parent, f"spec/{CHILD}") == ""


def test_a_predecessor_back_on_an_unchanged_head_restacks_nothing(
    store: UnitStore, logged: list[str], real: Stack
) -> None:
    sent_back(store, PARENT, Cause.BASE_CHANGED, FeedbackSource.NONE)
    follow(store, real.heads(), logged)
    assert store.get(CHILD).state == PLANNED
    real.parent_returns()

    assert real.restack_child() is None

    assert real.sha(f"spec/{CHILD}") == real.old_child
    assert store.get(CHILD).approved == real.old_child
