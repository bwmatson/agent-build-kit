"""The merge handler hands a moved child to the lane in place of restacking it inline.

The restack of a child starts at once on a lane worker, and a child whose resolver is
blocked holds up neither the rest of the poll nor a build. The merged unit's branch is kept
until the last child that named it has moved.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from agent_build_kit.pipeline import events
from agent_build_kit.pipeline.restack_lane import RestackLane
from agent_build_kit.pipeline.unit_store import Cause, HeldBy, StoredUnit, UnitStore
from agent_build_kit.pipeline.units import HELD, IN_REVIEW, PLANNED, RUNNING, SETTLING
from agent_build_kit.pipeline.workspaces import branch_lock
from tests.factories import stored_unit as unit
from tests.restack_lane_fakes import WAIT, Restacks, lane_over
from tests.restack_turn_fakes import run_bounded


class Blocked:
    """The restack the handler is given: it notes its kwargs and ends when released."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.begun = {"spec/c/2": threading.Event(), "spec/c/3": threading.Event()}
        self.release = threading.Event()

    def __call__(self, **kwargs: Any) -> None:
        self.calls.append(kwargs)
        self.begun[kwargs["branch"]].set()
        assert self.release.wait(WAIT)


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


@pytest.fixture
def moves() -> Restacks:
    return Restacks()


@pytest.fixture
def lane(locks: Path, moves: Restacks) -> Iterator[RestackLane]:
    with lane_over(locks, moves, cap=2) as lane:
        yield lane
        moves.release_all()
        lane.drain()


def merge(
    store: UnitStore, locks: Path, restack: Any, lane: RestackLane, *, pr: int = 1, **kwargs: Any
) -> bool:
    return events.on_merged(
        pr,
        repo="app",
        store=store,
        restack=restack,
        claim=events.build_claim(locks),
        lane=lane,
        log=lambda line: None,
        **kwargs,
    )


def test_a_merge_with_every_build_slot_taken_starts_the_childs_restack_at_once(
    store: UnitStore, locks: Path, lane: RestackLane
) -> None:
    restack = Blocked()

    with branch_lock("spec/c/9", root=locks):
        merge(store, locks, restack, lane)
        assert restack.begun["spec/c/2"].wait(WAIT)
        assert restack.begun["spec/c/3"].wait(WAIT)

        assert store.get("c/9").state == RUNNING
    restack.release.set()


def test_the_handler_does_not_hold_the_childs_claim_across_the_move(
    store: UnitStore, locks: Path, lane: RestackLane
) -> None:
    restack = Blocked()

    merge(store, locks, restack, lane)
    assert restack.begun["spec/c/2"].wait(WAIT)

    # The lane worker holds it, so a second claim on the branch is refused.
    with pytest.raises(events.BranchBusy), events.build_claim(locks)(store.get("c/2")):
        pass
    restack.release.set()


def test_a_child_whose_resolver_is_blocked_does_not_hold_up_the_poll(
    store: UnitStore, locks: Path, lane: RestackLane
) -> None:
    restack = Blocked()

    answer = run_bounded(lambda: merge(store, locks, restack, lane), seconds=WAIT)

    assert answer is True
    assert store.get("c/1").state == SETTLING
    assert restack.begun["spec/c/2"].wait(WAIT)
    assert not restack.release.is_set()
    restack.release.set()


def test_the_merged_units_branch_is_kept_until_the_last_child_has_moved(
    store: UnitStore, locks: Path, lane: RestackLane
) -> None:
    restack = Blocked()
    removed: list[tuple[str, str]] = []
    deleted: list[tuple[str, str]] = []

    merge(
        store,
        locks,
        restack,
        lane,
        remove_worktree=lambda repo, branch: removed.append((repo, branch)),
        delete_branch=lambda repo, branch: deleted.append((repo, branch)),
    )
    assert restack.begun["spec/c/2"].wait(WAIT)

    assert removed == []
    assert deleted == []

    restack.release.set()
    lane.drain()

    assert removed == [("app", "spec/c/1")]
    assert deleted == [("app", "spec/c/1")]


def test_a_child_that_could_not_be_moved_keeps_the_merged_units_branch(
    store: UnitStore, locks: Path, lane: RestackLane
) -> None:
    deleted: list[tuple[str, str]] = []

    def refused(**kwargs: Any) -> None:
        raise RuntimeError("push refused")

    merge(
        store,
        locks,
        refused,
        lane,
        remove_worktree=lambda repo, branch: None,
        delete_branch=lambda repo, branch: deleted.append((repo, branch)),
    )
    lane.drain()

    assert deleted == []


def test_a_child_with_a_thread_is_told_its_base_moved_and_handed_to_the_lane(
    store: UnitStore, locks: Path, lane: RestackLane, moves: Restacks
) -> None:
    told: list[tuple[str, str, str]] = []

    def resume(child: StoredUnit, kind: str, reason: str, feedback: str, **kwargs: Any) -> bool:
        told.append((child.id, kind, reason))
        return True

    restack = Blocked()
    merge(store, locks, restack, lane, resume=resume)
    assert moves.begun["c/2"].wait(WAIT)
    assert moves.begun["c/3"].wait(WAIT)

    assert ("c/2", "base_moved", "main") in told
    assert restack.calls == []


def test_a_restack_that_finds_a_rewritten_branch_still_moves_off_the_merged_base(
    store: UnitStore, locks: Path
) -> None:
    only_one = Restacks()
    restack = Blocked()
    with lane_over(locks, only_one, cap=1) as lane:
        blocker = unit("c/8", change="c")
        lane.hand_over(blocker)
        merge(store, locks, restack, lane)
        assert lane.waiting

        # While c/2 waits its turn a run finds the base moved and stops, leaving it planned.
        store.set_state("c/2", PLANNED, cause=Cause.BASE_CHANGED, branch="spec/c/2")
        only_one.release_all()
        assert restack.begun["spec/c/2"].wait(WAIT)
        restack.release.set()
        lane.drain()

    moved = {call["branch"]: call for call in restack.calls}
    assert moved["spec/c/2"]["old_base"] == "spec/c/1"
    assert moved["spec/c/2"]["new_base"] == "main"


def test_a_second_event_for_a_queued_child_moves_it_onto_the_base_it_has_when_it_starts(
    tmp_path: Path, locks: Path
) -> None:
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
    blocker = Restacks()
    calls: list[dict[str, Any]] = []

    def restack(**kwargs: Any) -> None:
        calls.append(kwargs)

    with lane_over(locks, blocker, cap=1) as lane:
        lane.hand_over(unit("c/8", change="c"))
        merge(store, locks, restack, lane, pr=2)  # c/1 merges: c/2 waits to move onto spec/c/0
        assert lane.waiting == ["c/2"]
        merge(store, locks, restack, lane, pr=1)  # c/0 merges before it starts
        assert lane.waiting == ["c/2"]
        blocker.release_all()
        lane.drain()

    assert [(call["old_base"], call["new_base"]) for call in calls] == [("spec/c/1", "main")]


def test_a_depth_held_unit_handed_over_keeps_the_merged_branch_until_it_has_moved(
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
    blocker = Restacks()
    deleted: list[tuple[str, str]] = []
    present_at_move: list[bool] = []

    def restack(**kwargs: Any) -> None:
        present_at_move.append(not deleted)

    with lane_over(locks, blocker, cap=1) as lane:
        lane.hand_over(unit("c/8", change="c"))
        merge(
            store,
            locks,
            restack,
            lane,
            pr=1,
            rebase_cap=3,
            remove_worktree=lambda repo, branch: None,
            delete_branch=lambda repo, branch: deleted.append((repo, branch)),
        )
        assert "c/4" in lane.waiting
        assert deleted == []

        blocker.release_all()
        lane.drain()

    assert present_at_move
    assert all(present_at_move)
    assert deleted == [("app", "spec/c/1")]
