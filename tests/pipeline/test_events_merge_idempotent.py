"""A merged event for a unit already recorded merged changes nothing.

The landing step and the poller both report a merge, in either order, and the
second must not restack, clean up or add to the history a second time.
"""

from collections.abc import Callable
from contextlib import nullcontext
from pathlib import Path

import pytest

from agent_build_kit.pipeline import events
from agent_build_kit.pipeline.unit_store import Cause, UnitStore
from agent_build_kit.pipeline.units import IN_REVIEW, RUNNING
from agent_build_kit.pipeline.workspaces import branch_lock
from tests.factories import stored_unit as unit


@pytest.fixture
def store(tmp_path: Path) -> UnitStore:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit("add-marker/1"), unit("add-marker/2", depends_on=("add-marker/1",))])
    store.set_state("add-marker/1", IN_REVIEW, pr=1, branch="spec/add-marker/1")
    store.set_state("add-marker/2", IN_REVIEW, pr=2, branch="spec/add-marker/2")
    return store


class Effects:
    """What a merge does outside the store."""

    def __init__(self) -> None:
        self.restacked: list[str] = []
        self.removed: list[str] = []
        self.deleted: list[str] = []
        self.retargeted: list[str] = []

    def merged(
        self,
        store: UnitStore,
        cause: Cause = Cause.MERGED,
        claim: Callable = lambda unit: nullcontext(),
    ) -> bool:
        return events.on_merged(
            1,
            repo="app",
            store=store,
            restack=lambda **k: self.restacked.append(k["branch"]),
            remove_worktree=lambda repo, branch: self.removed.append(branch),
            delete_branch=lambda repo, branch: self.deleted.append(branch),
            retarget=lambda u, base: self.retargeted.append(u.id),
            log=lambda m: None,
            cause=cause,
            claim=claim,
        )

    def counts(self) -> tuple[int, int, int, int]:
        return (
            len(self.restacked),
            len(self.removed),
            len(self.deleted),
            len(self.retargeted),
        )


@pytest.mark.parametrize(
    ("first", "second"),
    [
        (Cause.AUTO_LANDED, Cause.MERGED),
        (Cause.MERGED, Cause.AUTO_LANDED),
        (Cause.AUTO_LANDED, Cause.AUTO_LANDED),
        (Cause.MERGED, Cause.MERGED),
    ],
)
def test_a_second_merged_event_changes_nothing_whichever_came_first(
    store: UnitStore, first: Cause, second: Cause
) -> None:
    effects = Effects()
    effects.merged(store, cause=first)
    history = store.get("add-marker/1").history
    done = effects.counts()
    assert done[0] == 1, "the first event restacked the child"

    handled = effects.merged(store, cause=second)

    assert handled is True
    assert store.get("add-marker/1").history == history
    assert store.get("add-marker/1").cause == first
    assert effects.counts() == done


def test_a_unit_being_built_still_defers_the_merge_it_is_told_of(
    store: UnitStore, tmp_path: Path
) -> None:
    store.set_state("add-marker/1", RUNNING)
    effects = Effects()
    locks = tmp_path / "locks"

    with branch_lock("spec/add-marker/1", root=locks):
        handled = effects.merged(store, cause=Cause.AUTO_LANDED, claim=events.build_claim(locks))

    assert handled is False, "deferred, so it is reported again"
    assert store.get("add-marker/1").state == RUNNING
    assert effects.counts() == (0, 0, 0, 0)

    store.set_state("add-marker/1", IN_REVIEW)
    assert effects.merged(store, cause=Cause.AUTO_LANDED) is True
    assert store.get("add-marker/1").cause == Cause.AUTO_LANDED
