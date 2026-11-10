"""The merge handler records a moved child and starts nothing.

A child's restack is made later by a resolve worker, so the poll neither restacks nor hands the
child anywhere. The merged unit's branch is kept while a unit stacked on it is owed its move, and
removed on the first pass after the last has moved.
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

from agent_build_kit.pipeline import events
from agent_build_kit.pipeline.unit_store import Cause, HeldBy, StoredUnit, UnitStore
from agent_build_kit.pipeline.units import HELD, IN_REVIEW, MERGED, RUNNING, SETTLING
from agent_build_kit.pipeline.workspaces import branch_lock
from tests.factories import stored_unit as unit


class Restacks:
    """The restack the handler is given: it notes its kwargs, and must never be asked."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> None:
        self.calls.append(kwargs)


@pytest.fixture
def store(tmp_path: Path) -> UnitStore:
    """c/1 is open in review; c/2 and c/3 are stacked on it; c/9 is a build running."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert(
        [
            unit("c/1", change="c"),
            unit("c/2", change="c", depends_on=("c/1",)),
            unit("c/3", change="c", depends_on=("c/1",)),
            unit("c/9", change="c"),
        ]
    )
    for number in (1, 2, 3):
        store.set_state(f"c/{number}", IN_REVIEW, pr=number, branch=f"spec/c/{number}")
    store.set_state("c/9", RUNNING, branch="spec/c/9")
    return store


@pytest.fixture
def locks(tmp_path: Path) -> Path:
    return tmp_path / "locks"


def merge(store: UnitStore, locks: Path, restack: Any, *, pr: int = 1, **kwargs: Any) -> bool:
    return events.on_merged(
        pr,
        repo="app",
        store=store,
        restack=restack,
        claim=events.build_claim(locks),
        log=lambda line: None,
        **kwargs,
    )


def pass_over(
    store: UnitStore, locks: Path, removed: list, deleted: list, uid: str = "c/1"
) -> None:
    """The check each pass makes of a merged unit's branch."""
    events.remove_satisfied(
        store.get(uid),
        store=store,
        claim=events.build_claim(locks),
        remove_worktree=lambda repo, branch: removed.append((repo, branch)),
        delete_branch=lambda repo, branch: deleted.append((repo, branch)),
        on_new_base=lambda child: True,
        log=lambda line: None,
    )


def test_a_merge_with_every_build_slot_taken_records_each_child_and_restacks_nothing(
    store: UnitStore, locks: Path
) -> None:
    restack = Restacks()

    with branch_lock("spec/c/9", root=locks):
        merge(store, locks, restack)

        assert store.get("c/9").state == RUNNING

    assert restack.calls == []
    assert store.get("c/2").cause is Cause.BASE_CHANGED
    assert store.get("c/3").cause is Cause.BASE_CHANGED


def test_the_handler_answers_at_once_having_recorded_the_merge(
    store: UnitStore, locks: Path
) -> None:
    restack = Restacks()

    answer = merge(store, locks, restack)

    assert answer is True
    assert store.get("c/1").state == SETTLING
    assert restack.calls == []


def test_the_merged_units_branch_is_kept_until_the_last_child_has_moved(
    store: UnitStore, locks: Path
) -> None:
    removed: list[tuple[str, str]] = []
    deleted: list[tuple[str, str]] = []

    merge(
        store,
        locks,
        Restacks(),
        remove_worktree=lambda repo, branch: removed.append((repo, branch)),
        delete_branch=lambda repo, branch: deleted.append((repo, branch)),
    )
    store.set_state("c/1", MERGED)
    pass_over(store, locks, removed, deleted)

    assert removed == []
    assert deleted == []

    store.set_state("c/2", IN_REVIEW, cause=Cause.RESTACK_HANDED_BACK)
    pass_over(store, locks, removed, deleted)
    assert deleted == [], "c/3 is still owed its move"

    store.set_state("c/3", IN_REVIEW, cause=Cause.RESTACK_HANDED_BACK)
    pass_over(store, locks, removed, deleted)

    assert removed == [("app", "spec/c/1")]
    assert deleted == [("app", "spec/c/1")]


def test_a_child_that_could_not_be_recorded_keeps_the_merged_units_branch(
    store: UnitStore, locks: Path
) -> None:
    deleted: list[tuple[str, str]] = []
    claim = events.build_claim(locks)

    @contextmanager
    def refusing(child: StoredUnit) -> Any:
        if child.id == "c/2":
            raise RuntimeError("store refused")
        with claim(child):
            yield

    events.on_merged(
        1,
        repo="app",
        store=store,
        restack=Restacks(),
        claim=refusing,
        remove_worktree=lambda repo, branch: None,
        delete_branch=lambda repo, branch: deleted.append((repo, branch)),
        log=lambda line: None,
    )

    assert deleted == []
    assert store.get("c/3").cause is Cause.BASE_CHANGED, "the others are still recorded"


def test_a_child_with_a_thread_is_told_its_base_moved_and_nothing_is_started(
    store: UnitStore, locks: Path
) -> None:
    told: list[tuple[str, str, str]] = []
    deleted: list[tuple[str, str]] = []

    def resume(child: StoredUnit, kind: str, reason: str, feedback: str, **kwargs: Any) -> bool:
        told.append((child.id, kind, reason))
        return True

    restack = Restacks()
    merge(
        store,
        locks,
        restack,
        resume=resume,
        remove_worktree=lambda repo, branch: None,
        delete_branch=lambda repo, branch: deleted.append((repo, branch)),
    )

    assert ("c/2", "base_moved", "main") in told
    assert restack.calls == []
    assert deleted == [], "the thread has yet to move the branch"


def test_a_second_event_for_a_recorded_child_changes_nothing(tmp_path: Path, locks: Path) -> None:
    store = UnitStore(tmp_path / "units.json")
    store.upsert(
        [
            unit("c/0", change="c"),
            unit("c/1", change="c", depends_on=("c/0",)),
            unit("c/2", change="c", depends_on=("c/1",)),
        ]
    )
    for number in (0, 1, 2):
        store.set_state(f"c/{number}", IN_REVIEW, pr=number + 1, branch=f"spec/c/{number}")
    restack = Restacks()

    merge(store, locks, restack, pr=2)  # c/1 merges: c/2 is owed a move onto spec/c/0
    assert store.get("c/2").cause is Cause.BASE_CHANGED
    merge(store, locks, restack, pr=1)  # c/0 merges before it has moved

    assert restack.calls == []
    assert store.get("c/2").cause is Cause.BASE_CHANGED


def test_a_depth_held_unit_freed_by_the_merge_keeps_the_merged_branch_until_a_child_has_moved(
    tmp_path: Path, locks: Path
) -> None:
    store = UnitStore(tmp_path / "units.json")
    store.upsert(
        [
            unit("c/1", change="c"),
            unit("c/2", change="c", depends_on=("c/1",)),
            unit("c/4", change="c", depends_on=("c/2",)),
        ]
    )
    for number in (1, 2):
        store.set_state(f"c/{number}", IN_REVIEW, pr=number, branch=f"spec/c/{number}")
    # Held for depth on the branch of c/1, which is merging, and now within the cap.
    store.set_state(
        "c/4",
        HELD,
        pr=4,
        branch="spec/c/4",
        held_by=HeldBy.DEPTH,
        held_base="spec/c/1",
        cause=Cause.DEPTH,
    )
    deleted: list[tuple[str, str]] = []
    present_at_move: list[bool] = []

    def restack(**kwargs: Any) -> None:
        present_at_move.append(not deleted)

    merge(
        store,
        locks,
        restack,
        pr=1,
        rebase_cap=3,
        remove_worktree=lambda repo, branch: None,
        delete_branch=lambda repo, branch: deleted.append((repo, branch)),
    )

    assert store.get("c/2").cause is Cause.BASE_CHANGED
    assert all(present_at_move)
    assert deleted == [], "c/2 is owed its move off the branch"
