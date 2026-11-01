"""The reconcile pass: a unit's recorded pull request compared with the poller's cache.

The cache is what the poller last read from the forge. A merge the unit never recorded
(reported while it was being built, or missed) is handed to the poller's own dispatch,
so every effect of a merge happens as for any other. The pass never writes a unit's
state itself.
"""

from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path

import pytest

from agent_build_kit.forges import PullRequest
from agent_build_kit.pipeline.events import build_dispatch
from agent_build_kit.pipeline.pr_poller import PrState, snapshot, state_path
from agent_build_kit.pipeline.pr_reconcile import reconcile
from agent_build_kit.pipeline.unit_store import Cause, HeldBy, UnitStore
from agent_build_kit.pipeline.units import (
    CLOSED,
    FAILED,
    HELD,
    IN_REVIEW,
    MERGED,
    RUNNING,
    SETTLING,
    UnitState,
)
from agent_build_kit.pipeline.workspaces import BranchBusy
from tests.factories import stored_unit

MERGE_COMMIT = "9f2c1ab"


class Dispatches:
    """The poller's dispatch over the real handlers, counting what it is handed. A busy
    one holds every branch, as a running build does."""

    def __init__(self, store: UnitStore, busy: bool = False) -> None:
        self.events: list[tuple[str, int, str]] = []

        def claim(unit):
            if busy:
                raise BranchBusy("being built")
            return nullcontext()

        self.real = build_dispatch(
            store,
            restack=lambda **kwargs: None,
            claim=claim,
            merge_record=lambda unit: (MERGE_COMMIT, 7),
            log=lambda message: None,
        )

    def __call__(self, event: str, number: int, *, repo: str, **kwargs) -> bool:
        self.events.append((event, number, repo))
        return self.real(event, number, repo=repo, **kwargs)


def cache(state_dir: Path, repo: str, **states: str) -> None:
    """The poller's snapshot of `repo`: pull request number to the state the forge showed."""
    PrState.save(
        state_path(state_dir, repo),
        {
            number: snapshot(
                PullRequest(
                    number=int(number), head=f"spec/feature/{number}", base="main", state=state
                )
            )
            for number, state in states.items()
        },
        repo,
    )


@pytest.fixture
def store(tmp_path: Path) -> UnitStore:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([stored_unit("feature/1"), stored_unit("feature/2")])
    return store


@pytest.fixture
def state_dir(tmp_path: Path) -> Path:
    return tmp_path / "state"


def put(store: UnitStore, uid: str, state: UnitState, pr: int) -> None:
    held = HeldBy.REVIEW if state == HELD else HeldBy.NONE
    store.set_state(uid, state, pr=pr, branch=f"spec/{uid}", held_by=held)


@pytest.mark.parametrize("state", [RUNNING, IN_REVIEW, FAILED, HELD])
def test_a_merged_pull_request_is_recorded_once_through_on_merged(
    store: UnitStore, state_dir: Path, state: UnitState
) -> None:
    put(store, "feature/1", state, 1)
    cache(state_dir, "app", **{"1": "merged"})
    dispatch = Dispatches(store)
    history = len(store.get("feature/1").history)

    corrections = reconcile(store=store, state_dir=state_dir, dispatch=dispatch, log=lambda m: None)

    unit = store.get("feature/1")
    assert dispatch.events == [("merged", 1, "app")]
    assert [(c.unit, c.pr, c.event) for c in corrections] == [("feature/1", 1, "merged")]
    assert unit.state == SETTLING
    assert unit.cause == Cause.MERGED
    assert unit.merge_sha == MERGE_COMMIT
    assert len(unit.history) > history, "a history entry says what happened"


def test_a_second_pass_changes_nothing(store: UnitStore, state_dir: Path) -> None:
    put(store, "feature/1", IN_REVIEW, 1)
    cache(state_dir, "app", **{"1": "merged"})
    dispatch = Dispatches(store)
    reconcile(store=store, state_dir=state_dir, dispatch=dispatch, log=lambda m: None)
    recorded = store.get("feature/1")

    again = reconcile(store=store, state_dir=state_dir, dispatch=dispatch, log=lambda m: None)

    assert again == []
    assert store.get("feature/1") == recorded
    assert len(dispatch.events) == 1, "the handler was not told a second time"


def test_an_open_pull_request_changes_nothing(store: UnitStore, state_dir: Path) -> None:
    put(store, "feature/1", IN_REVIEW, 1)
    cache(state_dir, "app", **{"1": "open"})
    dispatch = Dispatches(store)
    before = store.get("feature/1")

    corrections = reconcile(store=store, state_dir=state_dir, dispatch=dispatch, log=lambda m: None)

    assert corrections == []
    assert dispatch.events == []
    assert store.get("feature/1") == before


def test_a_pull_request_closed_unmerged_follows_the_closed_path(
    store: UnitStore, state_dir: Path
) -> None:
    put(store, "feature/1", IN_REVIEW, 1)
    cache(state_dir, "app", **{"1": "closed"})
    dispatch = Dispatches(store)

    corrections = reconcile(store=store, state_dir=state_dir, dispatch=dispatch, log=lambda m: None)

    assert dispatch.events == [("closed", 1, "app")]
    assert [(c.unit, c.event) for c in corrections] == [("feature/1", "closed")]
    assert store.get("feature/1").state == CLOSED
    assert store.get("feature/1").merge_sha is None


def test_a_unit_being_built_is_left_for_a_later_pass(store: UnitStore, state_dir: Path) -> None:
    put(store, "feature/1", RUNNING, 1)
    cache(state_dir, "app", **{"1": "merged"})
    busy = Dispatches(store, busy=True)

    deferred = reconcile(store=store, state_dir=state_dir, dispatch=busy, log=lambda m: None)

    assert deferred == []
    assert store.get("feature/1").state == RUNNING

    free = Dispatches(store)
    later = reconcile(store=store, state_dir=state_dir, dispatch=free, log=lambda m: None)

    assert [c.unit for c in later] == ["feature/1"]
    assert store.get("feature/1").state == SETTLING


@pytest.mark.parametrize("state", [SETTLING, MERGED])
def test_a_unit_already_settling_or_merged_is_untouched(
    store: UnitStore, state_dir: Path, state: UnitState
) -> None:
    put(store, "feature/1", state, 1)
    cache(state_dir, "app", **{"1": "merged"})
    dispatch = Dispatches(store)
    before = store.get("feature/1")

    corrections = reconcile(store=store, state_dir=state_dir, dispatch=dispatch, log=lambda m: None)

    assert corrections == []
    assert dispatch.events == []
    assert store.get("feature/1") == before


def test_a_pull_request_of_another_repos_unit_is_not_matched(
    store: UnitStore, state_dir: Path
) -> None:
    """Numbers are per repo: #1 merged in `app` is not #1 of `platform`."""
    store.upsert([stored_unit("feature/3", repo="platform")])
    put(store, "feature/3", IN_REVIEW, 1)
    cache(state_dir, "app", **{"1": "merged"})
    dispatch = Dispatches(store)

    corrections = reconcile(store=store, state_dir=state_dir, dispatch=dispatch, log=lambda m: None)

    assert corrections == []
    assert store.get("feature/3").state == IN_REVIEW


def test_only_limits_the_pass_to_one_unit(store: UnitStore, state_dir: Path) -> None:
    put(store, "feature/1", IN_REVIEW, 1)
    put(store, "feature/2", IN_REVIEW, 2)
    cache(state_dir, "app", **{"1": "merged", "2": "merged"})

    corrections = reconcile(
        store=store,
        state_dir=state_dir,
        dispatch=Dispatches(store),
        only="feature/2",
        log=lambda m: None,
    )

    assert [c.unit for c in corrections] == ["feature/2"]
    assert store.get("feature/1").state == IN_REVIEW


def test_a_dry_run_reports_and_writes_nothing(store: UnitStore, state_dir: Path) -> None:
    put(store, "feature/1", IN_REVIEW, 1)
    cache(state_dir, "app", **{"1": "merged"})
    dispatch = Dispatches(store)
    before = store.get("feature/1")

    corrections = reconcile(
        store=store, state_dir=state_dir, dispatch=dispatch, dry_run=True, log=lambda m: None
    )

    assert [(c.unit, c.event) for c in corrections] == [("feature/1", "merged")]
    assert dispatch.events == []
    assert store.get("feature/1") == before
