"""The store takes records from another store whole, and gives named ones up."""

import json

import pytest

from agent_build_kit.pipeline.file_lock import try_file_lock
from agent_build_kit.pipeline.unit_store import UnitStore
from tests.factories import new_unit

HISTORY = (
    {"state": "running", "at": "2026-01-01T10:00:00+00:00"},
    {"state": "in_review", "at": "2026-01-01T11:00:00+00:00", "note": "pushed"},
    {"state": "merged", "at": "2026-01-02T09:00:00+00:00"},
)


def merged_unit(uid="moves/1", **overrides):
    return new_unit(
        uid,
        **{
            "state": "merged",
            "branch": f"spec/{uid}",
            "pr": 12,
            "flag": "narrow",
            "calibrated_lines": 180,
            "actual_lines": 150,
            "history": HISTORY,
            **overrides,
        },
    )


def test_import_keeps_every_field_of_a_merged_unit(tmp_path):
    unit = merged_unit()

    UnitStore(tmp_path / "units.json").import_units([unit])

    assert UnitStore(tmp_path / "units.json").get("moves/1") == unit


def test_import_writes_the_stores_own_format(tmp_path):
    path = tmp_path / "units.json"
    path.write_text(json.dumps({"units": []}))

    UnitStore(path).import_units([merged_unit()])

    text = path.read_text()
    assert text == json.dumps(json.loads(text), indent=2) + "\n"
    (record,) = json.loads(text)["units"]
    assert "priority" not in record
    assert record["state"] == "merged"


def test_an_equal_record_is_skipped(tmp_path):
    path = tmp_path / "units.json"
    store = UnitStore(path)
    store.import_units([merged_unit(), merged_unit("moves/2")])
    before = path.read_bytes()

    store.import_units([merged_unit()])

    assert path.read_bytes() == before
    assert [u.id for u in store.all()] == ["moves/1", "moves/2"]


def test_a_differing_record_with_the_same_id_is_a_conflict_naming_the_id_and_writes_nothing(
    tmp_path,
):
    path = tmp_path / "units.json"
    store = UnitStore(path)
    store.import_units([merged_unit()])
    before = path.read_bytes()

    with pytest.raises(ValueError, match="moves/1"):
        store.import_units([merged_unit("moves/9"), merged_unit(state="failed")])

    assert path.read_bytes() == before


def test_remove_units_removes_the_named_ids_only(tmp_path):
    store = UnitStore(tmp_path / "units.json")
    store.import_units([merged_unit(), merged_unit("moves/2"), merged_unit("keeps/1")])

    store.remove_units(["moves/1", "moves/2"])

    assert [u.id for u in store.all()] == ["keeps/1"]


@pytest.mark.parametrize("operation", ["import_units", "remove_units"])
def test_each_runs_under_the_stores_lock_and_calls_on_write(tmp_path, operation):
    path = tmp_path / "units.json"
    held: list[bool] = []
    written: list[list[str]] = []

    def on_write(units):
        with try_file_lock(path.with_name("units.json.lock")) as free:
            held.append(not free)
        written.append([u.id for u in units])

    store = UnitStore(path, on_write=on_write)
    store.import_units([merged_unit(), merged_unit("moves/2")])
    held.clear()
    written.clear()

    if operation == "import_units":
        store.import_units([merged_unit("moves/3")])
    else:
        store.remove_units(["moves/2"])

    assert held == [True]
    assert len(written) == 1
