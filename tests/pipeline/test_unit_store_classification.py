"""A review round's classification and drivers in the store (spec: review-classification)."""

import json
from pathlib import Path

import pytest

from agent_build_kit.pipeline.unit_store import UnitStore
from tests.factories import activate_with, unit
from tests.pipeline.test_stack_runner import Recorder, make_runner

UNIT_ID = unit().id


@pytest.fixture(autouse=True)
def review_enabled() -> None:
    activate_with(review={"enabled": True})


def reply(**fields: object) -> str:
    return json.dumps({"approved": True, "feedback": "", **fields})


def weighing(tmp_path: Path):
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    return store, make_runner(store, Recorder(), tmp_path)


def test_a_round_stores_the_classification_and_drivers_with_its_approval(tmp_path: Path) -> None:
    store, runner = weighing(tmp_path)

    runner.weigh_review(
        unit(), reply(classification="light", drivers=["src/app/marker.py"]), judged="sha-1"
    )

    stored = UnitStore(store.path).get(UNIT_ID)
    assert (stored.approved, stored.classification) == ("sha-1", "light")
    assert stored.drivers == ("src/app/marker.py",)


def test_a_later_round_replaces_them(tmp_path: Path) -> None:
    store, runner = weighing(tmp_path)
    runner.weigh_review(
        unit(), reply(classification="light", drivers=["src/app/marker.py"]), judged="sha-1"
    )

    runner.weigh_review(unit(), reply(classification="auto"), judged="sha-2")

    stored = store.get(UNIT_ID)
    assert (stored.approved, stored.classification) == ("sha-2", "auto")
    assert stored.drivers == ()


def test_an_approval_with_no_classification_records_full(tmp_path: Path) -> None:
    store, runner = weighing(tmp_path)

    runner.weigh_review(unit(), reply(), judged="sha-1")

    assert store.get(UNIT_ID).classification == "full"


def test_with_review_disabled_an_approval_records_no_classification(tmp_path: Path) -> None:
    activate_with(review={"enabled": False})
    store, runner = weighing(tmp_path)

    runner.weigh_review(unit(), reply(classification="light", drivers=["a.py"]), judged="sha-1")

    stored = store.get(UNIT_ID)
    assert (stored.approved, stored.classification, stored.drivers) == ("sha-1", None, ())


def test_a_record_written_before_classifications_reads_as_none_until_a_round_records_one(
    tmp_path: Path,
) -> None:
    store, runner = weighing(tmp_path)
    raw = json.loads(store.path.read_text())
    raw["units"][0].pop("classification", None)
    raw["units"][0].pop("drivers", None)
    store.path.write_text(json.dumps(raw))
    stored = UnitStore(store.path).get(UNIT_ID)
    assert (stored.classification, stored.drivers) == (None, ())

    runner.weigh_review(unit(), reply(classification="auto"), judged="sha-1")

    assert UnitStore(store.path).get(UNIT_ID).classification == "auto"
