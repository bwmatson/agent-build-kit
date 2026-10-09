"""A unit's priority in the store.

Written whole by `model_dump`, a record holding a key an older release does not
know is refused by it, so the default is left out of the record: a store with no
unit off normal is the store of the release before priorities.
"""

import json

import pytest

from agent_build_kit.pipeline.unit_store import StoredUnit, UnitStore
from agent_build_kit.pipeline.units import IN_REVIEW, RUNNING, UnitState
from tests.factories import unit

UNIT_ID = "add-marker/1"


def records(store: UnitStore) -> list[dict]:
    return json.loads(store.path.read_text())["units"]


def test_a_record_without_the_field_reads_as_normal(tmp_path) -> None:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit(UNIT_ID)])
    raw = json.loads(store.path.read_text())
    raw["units"][0].pop("priority", None)
    store.path.write_text(json.dumps(raw))

    assert UnitStore(store.path).get(UNIT_ID).priority == 3


def test_a_unit_at_normal_is_written_without_the_field(tmp_path) -> None:
    store = UnitStore(tmp_path / "units.json")

    store.upsert([unit(UNIT_ID), unit("add-marker/2", priority=3)])

    assert all("priority" not in record for record in records(store))


@pytest.mark.parametrize("value", [1, 2, 4, 5])
def test_a_unit_off_normal_round_trips(tmp_path, value) -> None:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit(UNIT_ID, priority=value)])

    assert UnitStore(store.path).get(UNIT_ID).priority == value
    assert records(store)[0]["priority"] == value


def test_a_later_write_keeps_the_priority_and_the_omission(tmp_path) -> None:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit(UNIT_ID, priority=2), unit("add-marker/2")])

    store.set_run_log(UNIT_ID, "run.log")
    store.set_run_log("add-marker/2", "run.log")

    written = {record["id"]: record for record in records(store)}
    assert written[UNIT_ID]["priority"] == 2
    assert "priority" not in written["add-marker/2"]


def test_an_older_release_reads_a_store_with_no_unit_off_normal(tmp_path, monkeypatch) -> None:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit(UNIT_ID), unit("add-marker/2")])
    # A release before priorities has no such field, so its check meets the key.
    monkeypatch.delitem(StoredUnit.model_fields, "priority", raising=False)

    assert [u.id for u in UnitStore(store.path).all()] == [UNIT_ID, "add-marker/2"]


def test_an_older_release_refuses_a_priority_with_the_usual_message(tmp_path, monkeypatch) -> None:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit(UNIT_ID, priority=2)])
    monkeypatch.delitem(StoredUnit.model_fields, "priority", raising=False)

    with pytest.raises(ValueError) as refused:
        UnitStore(store.path).all()

    message = str(refused.value)
    assert "newer release" in message
    assert UNIT_ID in message
    assert "priority" in message


@pytest.mark.parametrize("how", ["branch", RUNNING, IN_REVIEW])
def test_a_unit_that_has_started_keeps_its_priority_when_replanned(tmp_path, how) -> None:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit(UNIT_ID, priority=4)])
    if how == "branch":
        store.set_state(UNIT_ID, UnitState.PLANNED, branch="spec/add-marker/1")
    else:
        store.set_state(UNIT_ID, how, branch="spec/add-marker/1", pr=4)

    store.upsert([unit(UNIT_ID, priority=1)])

    assert store.get(UNIT_ID).priority == 4


def test_a_unit_that_has_started_at_normal_keeps_it_when_replanned(tmp_path) -> None:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit(UNIT_ID)])
    store.set_state(UNIT_ID, RUNNING, branch="spec/add-marker/1")

    store.upsert([unit(UNIT_ID, priority=1)])

    assert store.get(UNIT_ID).priority == 3
    assert "priority" not in records(store)[0]


def test_a_unit_that_has_not_started_takes_the_new_priority(tmp_path) -> None:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit(UNIT_ID, priority=4)])

    store.upsert([unit(UNIT_ID, priority=1)])

    assert store.get(UNIT_ID).priority == 1


def test_an_unstarted_unit_planned_back_to_normal_loses_the_field(tmp_path) -> None:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit(UNIT_ID, priority=1)])

    store.upsert([unit(UNIT_ID)])

    assert store.get(UNIT_ID).priority == 3
    assert "priority" not in records(store)[0]
