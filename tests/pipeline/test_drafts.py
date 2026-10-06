"""A unit's pull request, a draft while the pipeline works on it.

The forge is the stand-in, which logs each draft call and keeps each pull
request's state. Drafts are cosmetic: no failure of one is a unit's problem.
"""

from pathlib import Path

import pytest

from agent_build_kit.pipeline.drafts import StateDrafts
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import (
    CLOSED,
    FAILED,
    HELD,
    IN_REVIEW,
    MERGED,
    PLANNED,
    RUNNING,
    SATISFIED,
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
    """A store whose state changes reach the forge, as `cli.store_for` builds it."""
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


@pytest.mark.parametrize("state", [PLANNED, HELD, FAILED, MERGED, CLOSED, SATISFIED])
def test_the_other_states_make_no_call(state: str, store: UnitStore, forge: StandInForge) -> None:
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
