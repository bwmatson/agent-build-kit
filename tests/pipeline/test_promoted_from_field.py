"""`promoted_from` on a stored unit: the waiter that gives it its priority.

Like the default priority, an empty source is left out of the record, so a store with no
promoted unit is the store of the release before it, and a record without it reads as empty.
"""

import json

from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import RUNNING
from tests.factories import stored_unit, unit

UNIT_ID = "add-marker/1"
OTHER_ID = "add-marker/2"
WAITER = "add-marker/9"


def records(store: UnitStore) -> dict[str, dict]:
    return {record["id"]: record for record in json.loads(store.path.read_text())["units"]}


def test_the_source_is_empty_by_default_left_out_when_empty_and_kept_when_set(tmp_path) -> None:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit(UNIT_ID, priority=3), unit(WAITER, priority=1)])
    assert stored_unit(UNIT_ID).promoted_from == ""
    assert "promoted_from" not in records(store)[UNIT_ID]

    store.set_promotion(UNIT_ID, 1, WAITER)

    assert records(store)[UNIT_ID]["promoted_from"] == WAITER
    assert "promoted_from" not in records(store)[WAITER]
    assert UnitStore(store.path).get(UNIT_ID).promoted_from == WAITER


def test_a_store_written_before_the_field_reads_it_as_empty(tmp_path) -> None:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit(UNIT_ID)])
    assert "promoted_from" not in records(store)[UNIT_ID]
    raw = json.loads(store.path.read_text())
    raw["units"][0].pop("promoted_from", None)
    store.path.write_text(json.dumps(raw))

    assert UnitStore(store.path).get(UNIT_ID).promoted_from == ""


def test_upsert_gives_an_unstarted_unit_an_empty_source_and_keeps_a_started_ones(tmp_path) -> None:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit(UNIT_ID, priority=3), unit(OTHER_ID, priority=3)])
    store.set_promotion(UNIT_ID, 1, WAITER)
    store.set_promotion(OTHER_ID, 1, WAITER)
    store.set_state(OTHER_ID, RUNNING, branch="spec/add-marker/2")

    store.upsert([unit(UNIT_ID, priority=3), unit(OTHER_ID, priority=3), unit("add-marker/3")])

    started = store.get(OTHER_ID)
    assert (started.priority, started.promoted_from) == (1, WAITER)
    assert (store.get(UNIT_ID).priority, store.get(UNIT_ID).promoted_from) == (3, "")
    assert store.get("add-marker/3").promoted_from == ""


def test_set_priority_clears_the_source_of_an_unstarted_unit_and_leaves_a_started_one(
    tmp_path,
) -> None:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit(UNIT_ID, priority=3), unit(OTHER_ID, priority=3)])
    store.set_promotion(UNIT_ID, 1, WAITER)
    store.set_promotion(OTHER_ID, 1, WAITER)
    store.set_state(OTHER_ID, RUNNING, branch="spec/add-marker/2")

    store.set_priority(UNIT_ID, 3)
    store.set_priority(OTHER_ID, 3)

    assert (store.get(UNIT_ID).priority, store.get(UNIT_ID).promoted_from) == (3, "")
    assert (store.get(OTHER_ID).priority, store.get(OTHER_ID).promoted_from) == (1, WAITER)
    assert "promoted_from" not in records(store)[UNIT_ID]


def test_set_promotion_does_nothing_to_a_started_unit(tmp_path) -> None:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit(UNIT_ID, priority=3)])
    store.set_state(UNIT_ID, RUNNING, branch="spec/add-marker/1")

    store.set_promotion(UNIT_ID, 1, WAITER)

    assert (store.get(UNIT_ID).priority, store.get(UNIT_ID).promoted_from) == (3, "")
