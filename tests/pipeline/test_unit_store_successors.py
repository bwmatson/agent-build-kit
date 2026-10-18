"""A unit a replan replaced records the units that carry its groups, in the write that
replaces it (spec: a-replaced-unit-points-to-its-successor)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_build_kit.pipeline.unit_store import StoredUnit, UnitStore
from agent_build_kit.pipeline.units import Member, UnitState, successors_of
from tests.factories import stored_unit

UNPLANNED = UnitState.UNPLANNED


def store_of(tmp_path: Path, *units: StoredUnit) -> UnitStore:
    store = UnitStore(tmp_path / "units.json")
    store.import_units(units)
    return store


def written(store: UnitStore, uid: str) -> dict:
    [record] = [r for r in json.loads(store.path.read_text())["units"] if r["id"] == uid]
    return record


def test_successors_are_the_other_units_that_carry_a_group_in_id_order() -> None:
    gone = stored_unit("x/3", change="x", groups=(3,), state=UNPLANNED)
    carriers = [
        stored_unit("x/9", change="x", groups=(3,), state=UnitState.MERGED),
        stored_unit("x/4", change="x", groups=(3,)),
        stored_unit("x/5", change="x", groups=(3,), state=UnitState.RUNNING),
        stored_unit("x/6", change="x", groups=(3,), state=UnitState.SATISFIED),
        stored_unit("y/1", change="y", groups=(1,), joined=(Member(change="x", groups=(3,)),)),
    ]
    others = [
        stored_unit("x/7", change="x", groups=(3,), state=UNPLANNED),
        stored_unit("x/8", change="x", groups=(3,), state=UnitState.RETIRED),
        stored_unit("x/10", change="x", groups=(3,), state=UnitState.CLOSED),
        stored_unit("x/11", change="x", groups=(4,)),
    ]

    found = successors_of(gone, [gone, *carriers, *others])

    assert found == ("x/4", "x/5", "x/6", "x/9", "y/1")


def test_a_join_records_the_new_unit_on_both_replaced_units(tmp_path: Path) -> None:
    store = store_of(
        tmp_path,
        stored_unit("x/3", change="x", groups=(3,)),
        stored_unit("x/4", change="x", groups=(4,)),
    )

    store.upsert([stored_unit("x/5", change="x", groups=(3, 4))], change="x")

    for uid in ("x/3", "x/4"):
        unit = store.get(uid)
        assert unit.state == UNPLANNED
        assert unit.superseded_by == ("x/5",)
        assert unit.history[-1]["note"] == "replaced by x/5"


def test_a_split_records_both_new_units(tmp_path: Path) -> None:
    store = store_of(tmp_path, stored_unit("x/3", change="x", groups=(3, 4)))

    store.upsert(
        [
            stored_unit("x/4", change="x", groups=(3,)),
            stored_unit("x/5", change="x", groups=(4,)),
        ],
        change="x",
    )

    assert store.get("x/3").superseded_by == ("x/4", "x/5")


def test_a_dropped_group_leaves_the_field_empty_and_out_of_the_file(tmp_path: Path) -> None:
    store = store_of(tmp_path, stored_unit("x/3", change="x", groups=(3,)))

    store.upsert([stored_unit("x/9", change="x", groups=(9,))], change="x")

    assert store.get("x/3").state == UNPLANNED
    assert store.get("x/3").superseded_by == ()
    assert "superseded_by" not in written(store, "x/3")


def test_a_merged_unit_that_carries_the_groups_is_the_successor(tmp_path: Path) -> None:
    store = store_of(
        tmp_path,
        stored_unit("x/3", change="x", groups=(3,)),
        stored_unit("x/4", change="x", groups=(3,), state=UnitState.MERGED),
    )

    store.upsert([], change="x")

    assert store.get("x/3").superseded_by == ("x/4",)


def test_a_field_that_is_set_is_not_overwritten(tmp_path: Path) -> None:
    store = store_of(
        tmp_path,
        stored_unit("x/3", change="x", groups=(3,), state=UNPLANNED, superseded_by=("x/5",)),
        stored_unit("x/5", change="x", groups=(3,)),
    )

    store.upsert([stored_unit("x/6", change="x", groups=(3,))], change="x")

    assert store.get("x/5").superseded_by == ("x/6",)
    assert store.get("x/3").superseded_by == ("x/5",)


def test_a_unit_the_plan_asks_for_again_is_planned_and_loses_the_field(tmp_path: Path) -> None:
    store = store_of(
        tmp_path,
        stored_unit(
            "x/3",
            change="x",
            groups=(3,),
            state=UNPLANNED,
            superseded_by=("x/5",),
            feedback="keep me",
            guidance="and me",
        ),
        stored_unit("x/5", change="x", groups=(3,)),
    )

    store.upsert([stored_unit("x/3", change="x", groups=(3,))], change="x")

    revived = store.get("x/3")
    assert revived.state == UnitState.PLANNED
    assert revived.superseded_by == ()
    assert (revived.feedback, revived.guidance) == ("keep me", "and me")
    assert "superseded_by" not in written(store, "x/3")


def test_a_retired_unit_keeps_its_field_and_gets_one_when_a_plan_carries_its_groups(
    tmp_path: Path,
) -> None:
    store = store_of(
        tmp_path,
        stored_unit(
            "x/3", change="x", groups=(3,), state=UnitState.RETIRED, superseded_by=("x/8",)
        ),
        stored_unit("x/4", change="x", groups=(4,), state=UnitState.RETIRED),
        stored_unit("x/6", change="x", groups=(6,), state=UnitState.RETIRED),
    )

    store.upsert([stored_unit("x/5", change="x", groups=(4,))], change="x")

    assert store.get("x/3").superseded_by == ("x/8",)
    assert store.get("x/4").superseded_by == ("x/5",)
    assert store.get("x/6").superseded_by == ()
    assert store.get("x/4").state == UnitState.RETIRED


def test_unplan_vanished_records_the_units_that_carry_the_groups(tmp_path: Path) -> None:
    store = store_of(
        tmp_path,
        stored_unit("x/3", change="x", groups=(3,)),
        stored_unit("y/1", change="y", groups=(1,), joined=(Member(change="x", groups=(3,)),)),
    )

    assert store.unplan_vanished({"y"}) == ["x/3"]

    assert store.get("x/3").state == UNPLANNED
    assert store.get("x/3").superseded_by == ("y/1",)


def test_a_record_that_holds_the_field_loads_and_is_written_with_it(tmp_path: Path) -> None:
    store = store_of(
        tmp_path,
        stored_unit("x/3", change="x", groups=(3,), state=UNPLANNED, superseded_by=("x/5",)),
        stored_unit("x/5", change="x", groups=(3,)),
    )

    store.set_run_log("x/5", "run.log")

    assert store.get("x/3").superseded_by == ("x/5",)
    assert written(store, "x/3")["superseded_by"] == ["x/5"]
    assert "superseded_by" not in written(store, "x/5")


def test_a_file_from_before_the_field_loads_empty_and_is_written_without_it(
    tmp_path: Path,
) -> None:
    store = store_of(tmp_path, stored_unit("x/5", change="x", groups=(3,)))
    raw = json.loads(store.path.read_text())
    raw["units"][0].pop("superseded_by", None)
    store.path.write_text(json.dumps(raw))

    assert store.get("x/5").superseded_by == ()
    store.set_run_log("x/5", "run.log")

    assert "superseded_by" not in written(store, "x/5")
    raw = json.loads(store.path.read_text())
    raw["units"][0]["from_newer_release"] = ["x"]
    store.path.write_text(json.dumps(raw))
    with pytest.raises(ValueError, match="from_newer_release"):
        store.all()
