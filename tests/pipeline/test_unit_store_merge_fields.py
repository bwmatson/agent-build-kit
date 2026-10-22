"""What the store keeps of a merge (spec: needs-can-wait-for-a-merge).

A unit records the commit its pull request merged as, the tick that saw it merge, and which
of its `Needs:` targets wait for a merge. A record from before the fields loads without them.
"""

import json

from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import MERGED
from tests.factories import unit

UNIT_ID = "feature/1"
SHA = "4f1c2a9d0b7e3c5a8d6f1e2b3c4a5d6e7f8091a2"


def seeded(tmp_path) -> UnitStore:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit(UNIT_ID)])
    return store


def test_a_new_unit_has_no_merge_record_until_it_is_set(tmp_path) -> None:
    store = seeded(tmp_path)
    before = store.get(UNIT_ID)

    store.set_merge_record(UNIT_ID, SHA, 7)

    assert (before.merge_sha, before.merged_tick, before.merge_needs) == (None, None, ())
    assert (store.get(UNIT_ID).merge_sha, store.get(UNIT_ID).merged_tick) == (SHA, 7)


def test_the_merge_record_and_merge_needs_round_trip_through_the_file(tmp_path) -> None:
    store = seeded(tmp_path)
    store.set_state(UNIT_ID, MERGED, branch="spec/feature/1", pr=4)

    store.set_merge_record(UNIT_ID, SHA, 7)
    store.set_needs(UNIT_ID, ["base/1", "shared/1"])
    store.set_merge_needs(UNIT_ID, ["shared/1"])

    reloaded = UnitStore(store.path).get(UNIT_ID)
    assert (reloaded.merge_sha, reloaded.merged_tick) == (SHA, 7)
    assert reloaded.needs == ("base/1", "shared/1")
    assert reloaded.merge_needs == ("shared/1",)


def test_a_record_written_before_the_fields_loads_with_them_empty(tmp_path) -> None:
    store = seeded(tmp_path)
    store.set_state(UNIT_ID, MERGED, branch="spec/feature/1", pr=4)
    store.set_merge_record(UNIT_ID, SHA, 7)
    store.set_merge_needs(UNIT_ID, ["shared/1"])
    raw = json.loads(store.path.read_text())
    for record in raw["units"]:
        for field in ("merge_sha", "merged_tick", "merge_needs"):
            record.pop(field)
    store.path.write_text(json.dumps(raw))

    loaded = UnitStore(store.path).get(UNIT_ID)

    assert (loaded.merge_sha, loaded.merged_tick, loaded.merge_needs) == (None, None, ())
    assert loaded.state == MERGED


def test_a_replan_keeps_the_merge_record_of_a_merged_unit(tmp_path) -> None:
    store = seeded(tmp_path)
    store.set_state(UNIT_ID, MERGED, branch="spec/feature/1", pr=4)
    store.set_merge_record(UNIT_ID, SHA, 7)

    store.upsert([unit(UNIT_ID)], change="feature")

    kept = store.get(UNIT_ID)
    assert (kept.state, kept.pr) == (MERGED, 4)
    assert (kept.merge_sha, kept.merged_tick) == (SHA, 7)
