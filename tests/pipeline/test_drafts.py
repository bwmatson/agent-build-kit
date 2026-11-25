"""A unit's pull request, a draft while the pipeline works on it.

The forge is the stand-in, which logs each draft call and keeps each pull
request's state. Drafts are cosmetic: no failure of one is a unit's problem.
"""

from collections.abc import Callable
from pathlib import Path

import pytest

from agent_build_kit.pipeline.drafts import StateDrafts
from agent_build_kit.pipeline.unit_store import Cause, StoredUnit, UnitStore
from agent_build_kit.pipeline.units import (
    CLOSED,
    FAILED,
    HELD,
    IN_REVIEW,
    MERGED,
    PLANNED,
    RUNNING,
    SATISFIED,
    UnitState,
)
from tests.factories import stored_unit as unit
from tests.forges.stand_in import StandInForge, lookup

PR = 7
UID = "add-marker/1"


class NoDraftsForge(StandInForge):
    """A host that keeps no drafts: the call is unimplemented."""

    def set_draft(self, *args, **kwargs) -> None:
        raise NotImplementedError


def draft_calls(forge: StandInForge) -> list[tuple[str, int]]:
    return [call for call in forge.calls if call[0] in ("draft", "ready")]


def wired(tmp_path: Path, forge: StandInForge, logged: list[str]) -> UnitStore:
    """A store whose state changes reach the forge, as `run_support.store_for` builds it."""
    drafts = StateDrafts(lookup(forge), log=logged.append)
    return UnitStore(
        tmp_path / "units.json",
        on_state=lambda unit, units, opened: drafts.follow(unit, units, opened=opened),
    )


@pytest.fixture
def forge() -> StandInForge:
    return StandInForge()


@pytest.fixture
def logged() -> list[str]:
    return []


@pytest.fixture
def store(tmp_path: Path, forge: StandInForge, logged: list[str]) -> UnitStore:
    built = wired(tmp_path, forge, logged)
    built.upsert([unit(UID)])
    return built


def in_review(store: UnitStore) -> None:
    """The change that first records the pull request: nothing to publish."""
    store.set_state(UID, IN_REVIEW, pr=PR, branch="spec/add-marker/1")


def test_a_running_unit_with_a_pull_request_makes_it_a_draft(
    store: UnitStore, forge: StandInForge
) -> None:
    in_review(store)

    store.set_state(UID, RUNNING)

    assert draft_calls(forge) == [("draft", PR)]
    assert forge.is_draft[PR] is True


def test_a_unit_back_in_review_publishes_its_pull_request(
    store: UnitStore, forge: StandInForge
) -> None:
    in_review(store)
    store.set_state(UID, RUNNING)

    store.set_state(UID, IN_REVIEW)

    assert draft_calls(forge) == [("draft", PR), ("ready", PR)]
    assert forge.is_draft[PR] is False


def test_the_change_that_first_records_the_pull_request_makes_no_call(
    store: UnitStore, forge: StandInForge
) -> None:
    in_review(store)

    assert forge.calls == []


def test_a_pull_request_first_recorded_on_a_running_unit_is_left_alone(
    store: UnitStore, forge: StandInForge
) -> None:
    store.set_state(UID, RUNNING, pr=PR, branch="spec/add-marker/1")

    assert forge.calls == []


def test_a_unit_with_no_pull_request_makes_no_call(store: UnitStore, forge: StandInForge) -> None:
    store.set_state(UID, RUNNING)
    store.set_state(UID, IN_REVIEW)

    assert forge.calls == []


@pytest.mark.parametrize("state", [HELD, FAILED, MERGED, CLOSED, SATISFIED])
def test_the_other_states_make_no_call(
    state: UnitState, store: UnitStore, forge: StandInForge
) -> None:
    in_review(store)

    store.set_state(UID, state)

    assert forge.calls == []


def test_a_unit_made_a_draft_and_then_failed_is_still_a_draft(
    store: UnitStore, forge: StandInForge
) -> None:
    in_review(store)
    store.set_state(UID, RUNNING)

    store.set_state(UID, FAILED)

    assert draft_calls(forge) == [("draft", PR)]
    assert forge.is_draft[PR] is True


def test_a_refused_draft_is_logged_and_the_state_change_stands(
    tmp_path: Path, logged: list[str]
) -> None:
    forge = StandInForge(draft_error=RuntimeError)
    store = wired(tmp_path, forge, logged)
    store.upsert([unit(UID)])
    in_review(store)

    store.set_state(UID, RUNNING)

    assert len(logged) == 1, logged
    assert "refuses drafts" in logged[0]
    assert store.get(UID).state == RUNNING


def test_a_host_with_no_drafts_says_so_once_over_two_state_changes(
    tmp_path: Path, logged: list[str]
) -> None:
    store = wired(tmp_path, NoDraftsForge(), logged)
    store.upsert([unit(UID)])
    in_review(store)

    store.set_state(UID, RUNNING)
    store.set_state(UID, IN_REVIEW)

    assert len(logged) == 1, logged
    assert "no drafts" in logged[0]
    assert store.get(UID).state == IN_REVIEW


def test_a_unit_set_back_to_planned_makes_its_pull_request_a_draft(
    store: UnitStore, forge: StandInForge
) -> None:
    in_review(store)

    store.set_state(UID, PLANNED, cause=Cause.UPSTREAM_WENT_BACK)

    assert draft_calls(forge) == [("draft", PR)]
    assert forge.is_draft[PR] is True


def test_a_planned_unit_back_in_review_publishes_its_pull_request(
    store: UnitStore, forge: StandInForge
) -> None:
    in_review(store)
    store.set_state(UID, PLANNED, cause=Cause.UPSTREAM_WENT_BACK)

    store.set_state(UID, IN_REVIEW)

    assert draft_calls(forge) == [("draft", PR), ("ready", PR)]
    assert forge.is_draft[PR] is False


def test_a_planned_unit_with_no_pull_request_makes_no_call(
    store: UnitStore, forge: StandInForge
) -> None:
    store.set_state(UID, PLANNED)

    assert forge.calls == []


def test_a_refused_draft_on_a_unit_set_back_to_planned_is_logged_and_the_state_stands(
    tmp_path: Path, logged: list[str]
) -> None:
    store = wired(tmp_path, StandInForge(draft_error=RuntimeError), logged)
    store.upsert([unit(UID)])
    in_review(store)

    store.set_state(UID, PLANNED, cause=Cause.UPSTREAM_WENT_BACK)

    assert len(logged) == 1, logged
    assert "refuses drafts" in logged[0]
    assert store.get(UID).state == PLANNED


def test_a_host_with_no_drafts_is_logged_when_a_unit_goes_back_to_planned(
    tmp_path: Path, logged: list[str]
) -> None:
    store = wired(tmp_path, NoDraftsForge(), logged)
    store.upsert([unit(UID)])
    in_review(store)

    store.set_state(UID, PLANNED, cause=Cause.UPSTREAM_WENT_BACK)

    assert len(logged) == 1, logged
    assert "no drafts" in logged[0]
    assert store.get(UID).state == PLANNED


class RefusingForge(StandInForge):
    """A host that refuses the next `refusals` draft changes and then accepts them."""

    def __init__(self, refusals: int) -> None:
        super().__init__()
        self.refusals = refusals

    def set_draft(self, repo, pr: int, draft: bool) -> None:
        if self.refusals:
            self.refusals -= 1
            raise RuntimeError("the stand-in host refuses this change")
        super().set_draft(repo, pr, draft)


def recorded_as(states: dict[tuple[str, int], bool]) -> Callable[[str, int], bool | None]:
    """The poll's record of each pull request's draft state; none for one it did not list."""
    return lambda repo, pr: states.get((repo, pr))


@pytest.mark.parametrize(
    ("state", "draft", "expected"),
    [
        (RUNNING, False, [("draft", PR)]),
        (PLANNED, False, [("draft", PR)]),
        (IN_REVIEW, True, [("ready", PR)]),
        (RUNNING, True, []),
        (PLANNED, True, []),
        (IN_REVIEW, False, []),
        (RUNNING, None, []),
        (PLANNED, None, []),
        (IN_REVIEW, None, []),
        (HELD, True, []),
        (HELD, False, []),
        (FAILED, True, []),
        (FAILED, False, []),
        (MERGED, True, []),
        (MERGED, False, []),
        (CLOSED, True, []),
        (CLOSED, False, []),
        (SATISFIED, True, []),
        (SATISFIED, False, []),
    ],
)
def test_the_reconcile_writes_only_a_pull_request_whose_recorded_state_differs(
    state: UnitState,
    draft: bool | None,
    expected: list[tuple[str, int]],
    forge: StandInForge,
    logged: list[str],
) -> None:
    drafts = StateDrafts(lookup(forge), log=logged.append)
    recorded = {} if draft is None else {("app", PR): draft}

    drafts.reconcile([unit(UID, state=state, pr=PR)], recorded_as(recorded), limit=20)

    assert draft_calls(forge) == expected
    assert logged == []


def test_the_reconcile_leaves_a_unit_with_no_pull_request_alone(
    forge: StandInForge, logged: list[str]
) -> None:
    drafts = StateDrafts(lookup(forge), log=logged.append)

    drafts.reconcile(
        [unit(UID, state=RUNNING, pr=None)], recorded_as({("app", PR): False}), limit=20
    )

    assert forge.calls == []


def test_a_refused_write_is_logged_once_per_state_wanted_and_retried_at_each_poll() -> None:
    forge = RefusingForge(refusals=2)
    logged: list[str] = []
    drafts = StateDrafts(lookup(forge), log=logged.append)
    units = [unit(UID, state=IN_REVIEW, pr=PR)]
    recorded = recorded_as({("app", PR): True})

    drafts.reconcile(units, recorded, limit=20)
    drafts.reconcile(units, recorded, limit=20)

    assert len(logged) == 1, logged
    assert f"#{PR}" in logged[0]
    assert "draft=False" in logged[0]
    assert forge.calls == []

    drafts.reconcile(units, recorded, limit=20)

    assert draft_calls(forge) == [("ready", PR)]
    assert forge.is_draft[PR] is False
    assert len(logged) == 1, logged

    forge.refusals = 1
    drafts.reconcile(units, recorded, limit=20)

    assert len(logged) == 2, logged
    assert f"#{PR}" in logged[1]


def test_the_reconcile_writes_the_limit_lowest_numbers_first_and_the_rest_next_time(
    forge: StandInForge, logged: list[str]
) -> None:
    drafts = StateDrafts(lookup(forge), log=logged.append)
    numbers = {"app": (5, 3), "platform": (4, 2)}
    units = [
        unit(f"{repo}-change/{pr}", repo=repo, state=RUNNING, pr=pr)
        for repo, prs in numbers.items()
        for pr in prs
    ]

    def recorded(repo: str, pr: int) -> bool | None:
        """What the next poll would read: ready until the forge was asked for a draft."""
        return forge.is_draft.get(pr, False)

    drafts.reconcile(units, recorded, limit=3)

    assert draft_calls(forge) == [("draft", 3), ("draft", 5), ("draft", 2)]

    drafts.reconcile(units, recorded, limit=3)

    assert draft_calls(forge)[3:] == [("draft", 4)]


def test_a_host_with_no_drafts_is_logged_once_over_two_reconciles(logged: list[str]) -> None:
    drafts = StateDrafts(lookup(NoDraftsForge()), log=logged.append)
    units: list[StoredUnit] = [unit(UID, state=RUNNING, pr=PR)]
    recorded = recorded_as({("app", PR): False})

    drafts.reconcile(units, recorded, limit=20)
    drafts.reconcile(units, recorded, limit=20)

    assert len(logged) == 1, logged
    assert "no drafts" in logged[0]
    assert units[0].state == RUNNING
