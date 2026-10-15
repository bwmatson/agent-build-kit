"""A unit parked before splits existed reads as parked on its splits, and new writes use only the
new names (spec: tier2-split-runs)."""

import json

from agent_build_kit.pipeline.unit_store import Cause, UnitStore
from agent_build_kit.pipeline.units import PLANNED
from tests.factories import unit

UNIT_ID = "add-marker/1"


def record(store: UnitStore) -> dict:
    return json.loads(store.path.read_text())["units"][0]


def older_store(tmp_path) -> UnitStore:
    """A store whose one unit was parked by the release that named runtimes."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit(UNIT_ID)])
    store.set_state(UNIT_ID, PLANNED, note="held", cause=Cause.SPLIT_HELD)
    raw = json.loads(store.path.read_text())
    old = raw["units"][0]
    old["history"][-1]["cause"] = "runtime_blocked"
    old["parked_runtimes"] = ["acp", "claude_code"]
    old["parked_sha"] = "sha-1"
    old["parked_snapshot"] = "first run"
    store.path.write_text(json.dumps(raw))
    return UnitStore(store.path)


def test_a_unit_parked_on_runtimes_reads_as_parked_on_the_same_splits(tmp_path) -> None:
    stored = older_store(tmp_path).get(UNIT_ID)

    assert stored.cause is Cause.SPLIT_HELD
    assert stored.parked_splits == ["acp", "claude_code"]
    assert (stored.parked_sha, stored.parked_snapshot) == ("sha-1", "first run")


def test_a_write_after_reading_an_older_record_keeps_only_the_new_names(tmp_path) -> None:
    store = older_store(tmp_path)

    store.set_parked(UNIT_ID, ["acp"], "sha-2", "second run")

    written = record(store)
    assert written["parked_splits"] == ["acp"]
    assert "parked_runtimes" not in written


def test_a_new_park_is_written_as_a_split_hold(tmp_path) -> None:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit(UNIT_ID)])

    store.set_state(UNIT_ID, PLANNED, note="held", cause=Cause.SPLIT_HELD)
    store.set_parked(UNIT_ID, ["acp"], "sha-1", "run")

    text = json.dumps(record(store))
    assert "parked_splits" in text and "parked_runtimes" not in text
    assert "split_held" in text and "runtime_blocked" not in text
    assert UnitStore(store.path).get(UNIT_ID).cause is Cause.SPLIT_HELD
