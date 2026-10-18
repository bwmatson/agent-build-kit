"""Units replaced before successors were recorded are given them once (spec:
a-replaced-unit-points-to-its-successor)."""

from __future__ import annotations

import json
from pathlib import Path

from agent_build_kit.pipeline.unit_store import StoredUnit, UnitStore
from agent_build_kit.pipeline.units import UnitState
from tests.factories import stored_unit

UNPLANNED = UnitState.UNPLANNED


def store_of(tmp_path: Path, writes: list[int], *units: StoredUnit) -> UnitStore:
    store = UnitStore(tmp_path / "units.json", on_write=lambda stored: writes.append(len(stored)))
    store.import_units(units)
    return store


def test_an_unplanned_unit_with_no_record_gets_the_unit_that_carries_its_groups(
    tmp_path: Path,
) -> None:
    store = store_of(
        tmp_path,
        [],
        stored_unit("x/3", change="x", groups=(3,), state=UNPLANNED),
        stored_unit("x/12", change="x", groups=(3,)),
    )

    assert store.backfill_successors() == ["x/3"]

    assert store.get("x/3").superseded_by == ("x/12",)


def test_several_units_are_written_once_and_returned(tmp_path: Path) -> None:
    writes: list[int] = []
    store = store_of(
        tmp_path,
        writes,
        stored_unit("x/3", change="x", groups=(3,), state=UNPLANNED),
        stored_unit("x/4", change="x", groups=(4,), state=UNPLANNED),
        stored_unit("x/12", change="x", groups=(3, 4)),
    )
    before = len(writes)

    assert store.backfill_successors() == ["x/3", "x/4"]

    assert len(writes) - before == 1
    assert store.get("x/4").superseded_by == ("x/12",)


def test_a_unit_nothing_carries_stays_empty_and_is_not_counted(tmp_path: Path) -> None:
    writes: list[int] = []
    store = store_of(tmp_path, writes, stored_unit("x/3", change="x", groups=(3,), state=UNPLANNED))
    before = len(writes)

    assert store.backfill_successors() == []

    assert store.get("x/3").superseded_by == ()
    assert len(writes) == before


def test_a_unit_that_has_successors_is_not_touched(tmp_path: Path) -> None:
    store = store_of(
        tmp_path,
        [],
        stored_unit("x/3", change="x", groups=(3,), state=UNPLANNED, superseded_by=("x/5",)),
        stored_unit("x/5", change="x", groups=(3,), state=UNPLANNED),
        stored_unit("x/6", change="x", groups=(3,)),
    )

    assert store.backfill_successors() == ["x/5"]

    assert store.get("x/3").superseded_by == ("x/5",)
    assert store.get("x/5").superseded_by == ("x/6",)


def test_a_second_call_writes_nothing(tmp_path: Path) -> None:
    writes: list[int] = []
    store = store_of(
        tmp_path,
        writes,
        stored_unit("x/3", change="x", groups=(3,), state=UNPLANNED),
        stored_unit("x/12", change="x", groups=(3,)),
    )
    assert store.backfill_successors() == ["x/3"]
    before = len(writes)

    assert store.backfill_successors() == []

    assert len(writes) == before


def test_a_retired_unit_gets_one_when_a_later_plan_carried_its_groups(tmp_path: Path) -> None:
    store = store_of(
        tmp_path,
        [],
        stored_unit("x/3", change="x", groups=(3,), state=UnitState.RETIRED),
        stored_unit("x/7", change="x", groups=(3,)),
    )

    assert store.backfill_successors() == ["x/3"]

    assert store.get("x/3").superseded_by == ("x/7",)
    assert store.get("x/3").state == UnitState.RETIRED


def test_a_units_file_from_before_the_field_is_backfilled_and_written_with_it(
    tmp_path: Path,
) -> None:
    store = store_of(
        tmp_path,
        [],
        stored_unit("x/3", change="x", groups=(3,), state=UNPLANNED),
        stored_unit("x/12", change="x", groups=(3,)),
    )
    raw = json.loads(store.path.read_text())
    for record in raw["units"]:
        record.pop("superseded_by", None)
    store.path.write_text(json.dumps(raw))

    assert store.backfill_successors() == ["x/3"]

    records = {r["id"]: r for r in json.loads(store.path.read_text())["units"]}
    assert records["x/3"]["superseded_by"] == ["x/12"]
    assert "superseded_by" not in records["x/12"]
