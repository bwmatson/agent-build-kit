"""The fields a hold-and-split keeps on a unit (spec: hold-and-split, unit-superseding)."""

from __future__ import annotations

import json
from pathlib import Path

from agent_build_kit.pipeline.unit_store import StoredSplitRequest, StoredUnit, UnitStore
from tests.factories import stored_unit, unit

UNIT_ID = unit().id
REQUEST = StoredSplitRequest(earned="full", planned="auto", lines=950, ceiling=750, drivers=(2, 3))


def split_fields() -> dict:
    return dict(
        split_request=REQUEST,
        split_rounds_used=1,
        size_waived=True,
        split_from="add-marker/0",
        superseded_by=("add-marker/1-s1", "add-marker/1-s2"),
    )


def test_the_request_the_rounds_the_waiver_and_the_lineage_round_trip(tmp_path: Path) -> None:
    store = UnitStore(tmp_path / "units.json")
    store.import_units([stored_unit(**split_fields())])

    stored = UnitStore(store.path).get(UNIT_ID)

    assert stored.split_request == REQUEST
    assert stored.split_rounds_used == 1
    assert stored.size_waived is True
    assert stored.split_from == "add-marker/0"
    assert stored.superseded_by == ("add-marker/1-s1", "add-marker/1-s2")


def test_upsert_keeps_them(tmp_path: Path) -> None:
    store = UnitStore(tmp_path / "units.json")
    kept = split_fields()
    del kept["superseded_by"]  # a unit the plan holds is live: it carries none (see `upsert`)
    store.import_units([stored_unit(**kept)])

    store.upsert([unit()])

    stored = store.get(UNIT_ID)
    assert stored.split_request == REQUEST
    assert stored.split_rounds_used == 1
    assert stored.size_waived is True
    assert stored.split_from == "add-marker/0"


def test_a_record_written_before_they_existed_loads_with_their_defaults(tmp_path: Path) -> None:
    store = UnitStore(tmp_path / "units.json")
    store.import_units([stored_unit()])
    raw = json.loads(store.path.read_text())
    for name in ("split_request", "split_rounds_used", "size_waived", "split_from"):
        raw["units"][0].pop(name, None)
    store.path.write_text(json.dumps(raw))

    stored: StoredUnit = UnitStore(store.path).get(UNIT_ID)

    assert stored.split_request is None
    assert stored.split_rounds_used == 0
    assert stored.size_waived is False
    assert stored.split_from == ""
