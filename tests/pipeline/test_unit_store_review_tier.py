"""A unit's planned review tier in the store.

The planner's estimate is kept by a re-plan of a started unit, and a record written
before review tiers existed reads as no estimate.
"""

import json

from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import RUNNING
from tests.factories import unit

UNIT_ID = "add-marker/1"


def records(store: UnitStore) -> list[dict]:
    return json.loads(store.path.read_text())["units"]


def test_the_estimate_round_trips_and_an_absent_one_is_left_out_of_the_record(tmp_path) -> None:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit(UNIT_ID, review_tier="light"), unit("add-marker/2")])

    assert UnitStore(store.path).get(UNIT_ID).review_tier == "light"
    written = {record["id"]: record for record in records(store)}
    assert written[UNIT_ID]["review_tier"] == "light"
    assert "review_tier" not in written["add-marker/2"]


def test_a_replan_gives_an_unstarted_unit_its_new_estimate_and_a_started_one_keeps_its_own(
    tmp_path,
) -> None:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit(UNIT_ID, review_tier="light"), unit("add-marker/2", review_tier="light")])
    store.set_state(UNIT_ID, RUNNING)

    store.upsert(
        [unit(UNIT_ID, review_tier="full"), unit("add-marker/2", review_tier="full")],
        change="add-marker",
    )

    assert store.get(UNIT_ID).review_tier == "light"
    assert store.get("add-marker/2").review_tier == "full"


def test_a_started_unit_planned_without_an_estimate_keeps_none(tmp_path) -> None:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit(UNIT_ID)])
    store.set_state(UNIT_ID, RUNNING)

    store.upsert([unit(UNIT_ID, review_tier="auto")], change="add-marker")

    assert store.get(UNIT_ID).review_tier is None


def test_a_record_written_before_review_tiers_reads_as_no_estimate(tmp_path) -> None:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit(UNIT_ID)])
    raw = json.loads(store.path.read_text())
    raw["units"][0].pop("review_tier", None)
    store.path.write_text(json.dumps(raw))

    assert UnitStore(store.path).get(UNIT_ID).review_tier is None
    store.set_run_log(UNIT_ID, "run.log")
    assert "review_tier" not in records(store)[0]
