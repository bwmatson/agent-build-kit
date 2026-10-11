"""A unit remembers when it became ready and when a person first answered
(spec: unit-timeline-is-recorded).

Start and entry into review are read from its history; the two fields are the only new
facts. The store they live in is committed and read by whichever release runs, so what an
older release does with them is part of the contract.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from agent_build_kit.forges import PullRequest
from agent_build_kit.pipeline.pr_poller import Poller
from agent_build_kit.pipeline.unit_store import Cause, StoredUnit, UnitStore
from agent_build_kit.pipeline.units import IN_REVIEW, PLANNED, RUNNING
from tests.factories import unit
from tests.fake_clock import START, FakeClock, install

UNIT_ID = "add-marker/1"


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> FakeClock:
    return install(monkeypatch)


@pytest.fixture
def store(tmp_path: Path, clock: FakeClock) -> UnitStore:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit(UNIT_ID)])
    return store


def written(store: UnitStore) -> dict:
    return json.loads(store.path.read_text())["units"][0]


# --- ready_at -------------------------------------------------------------------------


def test_ready_at_is_set_once_and_a_rework_or_later_wait_does_not_reset_it(
    store: UnitStore, clock: FakeClock
) -> None:
    store.mark_ready(UNIT_ID)
    assert store.get(UNIT_ID).ready_at == START

    clock.advance(3600)
    store.set_state(UNIT_ID, RUNNING, branch="spec/add-marker/1")
    store.set_state(UNIT_ID, IN_REVIEW, pr=7)
    store.set_state(UNIT_ID, PLANNED, note="rework requested", cause=Cause.REWORK)
    store.mark_ready(UNIT_ID)

    assert store.get(UNIT_ID).ready_at == START


# --- started_at and review_requested_at ---------------------------------------------------


def test_start_and_entry_into_review_are_read_from_the_history(
    store: UnitStore, clock: FakeClock
) -> None:
    clock.advance(60)
    store.set_state(UNIT_ID, RUNNING, branch="spec/add-marker/1")
    clock.advance(600)
    store.set_state(UNIT_ID, IN_REVIEW, pr=7)
    clock.advance(600)
    store.set_state(UNIT_ID, PLANNED, note="rework requested", cause=Cause.REWORK)
    clock.advance(600)
    store.set_state(UNIT_ID, RUNNING, branch="spec/add-marker/1")
    store.set_state(UNIT_ID, IN_REVIEW, pr=7)

    stored = store.get(UNIT_ID)

    assert stored.started_at == START + timedelta(seconds=60)
    assert stored.review_requested_at == START + timedelta(seconds=660)


def test_a_unit_that_never_ran_has_neither(store: UnitStore) -> None:
    stored = store.get(UNIT_ID)

    assert stored.started_at is None
    assert stored.review_requested_at is None


# --- first_human_activity_at --------------------------------------------------------------


def test_the_first_comment_of_a_person_stamps_the_time_it_was_seen(
    store: UnitStore, clock: FakeClock
) -> None:
    clock.advance(600)
    store.mark_human_activity(UNIT_ID)
    clock.advance(600)
    store.mark_human_activity(UNIT_ID)

    assert store.get(UNIT_ID).first_human_activity_at == START + timedelta(seconds=600)


def pull(number: int, *ids: str) -> PullRequest:
    return PullRequest(
        number=number,
        head=f"spec/add-marker/{number}",
        base="main",
        state="open",
        conversation=ids,
        comment_bodies=tuple(f"comment {i}" for i in ids),
    )


def test_only_a_comment_the_pipeline_did_not_post_reports_a_person_answering(
    tmp_path: Path,
) -> None:
    pulls = [
        pull(4, "c1", "c2"),  # every comment the pipeline's own
        pull(5, "c3", "c4"),  # one of them a person's
        pull(6),  # none
    ]
    own = {4: {"c1", "c2"}, 5: {"c3"}}
    answered: list[int] = []

    Poller(
        repo="app",
        state_path=tmp_path / "poll.json",
        list_prs=lambda: pulls,
        dispatch=lambda action, number, **_: None,
        ignore=lambda number: own.get(number, set()),
        human_activity=answered.append,
    ).poll()

    assert answered == [5]


# --- the store as an older release reads it ---------------------------------------------


def test_the_fields_round_trip_through_the_store(store: UnitStore, clock: FakeClock) -> None:
    store.mark_ready(UNIT_ID)
    clock.advance(30)
    store.mark_human_activity(UNIT_ID)

    again = UnitStore(store.path).get(UNIT_ID)

    assert again.ready_at == START
    assert again.first_human_activity_at == START + timedelta(seconds=30)
    assert isinstance(again.ready_at, datetime)


def test_the_written_record_omits_both_fields_while_they_are_unset(store: UnitStore) -> None:
    store.set_run_log(UNIT_ID, "run.log")

    record = written(store)

    assert "ready_at" not in record
    assert "first_human_activity_at" not in record


def test_the_written_record_holds_a_set_field_as_a_plain_value(store: UnitStore) -> None:
    store.mark_ready(UNIT_ID)

    record = written(store)

    assert datetime.fromisoformat(record["ready_at"]) == START
    assert "first_human_activity_at" not in record


@pytest.fixture
def older_release(monkeypatch: pytest.MonkeyPatch) -> None:
    """This release as one before the fields read a store: neither is a field of its."""
    for name in ("ready_at", "first_human_activity_at"):
        monkeypatch.delitem(StoredUnit.model_fields, name)


def test_an_older_release_reads_a_store_with_the_fields_unset(
    store: UnitStore, older_release: None
) -> None:
    store.set_run_log(UNIT_ID, "run.log")
    assert "ready_at" not in written(store), "the record this release writes carries neither"

    assert [u.id for u in UnitStore(store.path).all()] == [UNIT_ID]


def test_an_older_release_refuses_a_set_field_naming_the_unit_the_field_and_the_value(
    tmp_path: Path, clock: FakeClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit(UNIT_ID)])
    store.mark_ready(UNIT_ID)
    value = written(store)["ready_at"]
    for name in ("ready_at", "first_human_activity_at"):
        monkeypatch.delitem(StoredUnit.model_fields, name)

    with pytest.raises(ValueError) as refused:
        UnitStore(store.path).all()

    message = str(refused.value)
    assert UNIT_ID in message
    assert "ready_at" in message
    assert value in message
    assert "newer release" in message
