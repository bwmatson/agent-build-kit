"""A unit a replan replaced records the units that carry its groups, in the write that
replaces it (spec: a-replaced-unit-points-to-its-successor)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from agent_build_kit.pipeline.unit_store import StoredUnit, UnitStore
from agent_build_kit.pipeline.units import Member, UnitState, successors_of
from agent_build_kit.pipeline.unplanned_sweep import sweep
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


# The sweep (spec: unplanned-sweep): a demoted unit stays for the pass that demoted it, and the
# next pass removes it once nothing needs it.

AFTER = datetime.now(UTC) + timedelta(days=1)
BEFORE = datetime.now(UTC) - timedelta(days=1)


def demoted_by_a_replan(tmp_path: Path, *others: StoredUnit) -> UnitStore:
    """x/3 carried group 3, which x/4 now carries; a replan of x demotes x/3."""
    store = store_of(tmp_path, stored_unit("x/3", change="x", groups=(3,)), *others)
    store.upsert([stored_unit("x/4", change="x", groups=(3,))], change="x")
    assert store.get("x/3").state == UNPLANNED
    return store


def test_a_unit_demoted_in_a_pass_is_still_there_after_it_and_gone_after_the_next(
    tmp_path: Path,
) -> None:
    store = demoted_by_a_replan(tmp_path)

    assert sweep(store, active_changes={"x"}, pass_started=BEFORE) == []
    assert store.get("x/3").superseded_by == ("x/4",)

    assert sweep(store, active_changes={"x"}, pass_started=AFTER) == ["x/3"]
    assert "x/3" not in {unit.id for unit in store.all()}


@pytest.mark.parametrize(
    "field", ["depends_on", "needs", "merge_needs", "waited_on", "superseded_by"]
)
def test_a_reference_to_a_swept_unit_is_repointed_to_its_successor(
    tmp_path: Path, field: str
) -> None:
    store = demoted_by_a_replan(tmp_path, stored_unit("y/1", change="y", **{field: ("x/3",)}))

    sweep(store, active_changes={"x", "y"}, pass_started=AFTER)

    assert getattr(store.get("y/1"), field) == ("x/4",)
    assert "x/3" not in {unit.id for unit in store.all()}


def test_the_references_of_a_sweep_are_written_with_the_removal_in_one_write(
    tmp_path: Path,
) -> None:
    store = demoted_by_a_replan(tmp_path, stored_unit("y/1", change="y", depends_on=("x/3",)))
    before = store.path.stat().st_mtime_ns

    sweep(store, active_changes={"x", "y"}, pass_started=AFTER)

    assert store.path.stat().st_mtime_ns != before
    assert sweep(store, active_changes={"x", "y"}, pass_started=AFTER) == []


def test_a_sweep_that_removes_nothing_does_not_write_the_store(tmp_path: Path) -> None:
    store = demoted_by_a_replan(tmp_path)
    before = store.path.stat().st_mtime_ns

    assert sweep(store, active_changes={"x"}, pass_started=BEFORE) == []

    assert store.path.stat().st_mtime_ns == before


@pytest.mark.parametrize("passes", [1, 3])
def test_what_holds_work_or_is_in_another_state_or_is_the_last_unit_survives(
    tmp_path: Path, passes: int
) -> None:
    store = store_of(
        tmp_path,
        stored_unit("a/1", change="a", groups=(1,), state=UNPLANNED, branch="spec/a/1"),
        stored_unit("b/1", change="b", groups=(1,), state=UnitState.MERGED),
        stored_unit("c/1", change="c", groups=(1,), state=UnitState.RETIRED),
        stored_unit("d/1", change="d", groups=(), state=UNPLANNED),
    )

    for _ in range(passes):
        sweep(store, active_changes={"a", "b", "c", "d"}, pass_started=AFTER)

    assert {unit.id for unit in store.all()} == {"a/1", "b/1", "c/1", "d/1"}


def test_the_tombstones_of_an_archived_change_go(tmp_path: Path) -> None:
    store = demoted_by_a_replan(tmp_path)

    assert sweep(store, active_changes=set(), pass_started=AFTER) == ["x/3"]


def test_a_tracker_that_has_not_reconciled_since_the_demotion_keeps_the_unit(
    tmp_path: Path,
) -> None:
    store = demoted_by_a_replan(tmp_path)

    kept = sweep(
        store,
        active_changes={"x"},
        pass_started=AFTER,
        tracker_configured=True,
        tracker_reconciled=BEFORE,
    )
    assert kept == []

    removed = sweep(
        store,
        active_changes={"x"},
        pass_started=AFTER,
        tracker_configured=True,
        tracker_reconciled=AFTER,
    )
    assert removed == ["x/3"]


def test_a_dry_sweep_reports_the_verdicts_and_changes_nothing(tmp_path: Path) -> None:
    store = demoted_by_a_replan(tmp_path)
    before = store.path.read_text()

    found = sweep(store, active_changes={"x"}, pass_started=AFTER, dry_run=True)

    assert found == ["x/3"]
    assert store.path.read_text() == before


def test_a_unit_named_with_no_successor_stays_and_so_does_what_names_it_only_through_it(
    tmp_path: Path,
) -> None:
    store = store_of(
        tmp_path,
        stored_unit("x/3", change="x", groups=(3,), state=UNPLANNED),
        stored_unit("x/4", change="x", groups=(4,), state=UNPLANNED, depends_on=("x/3",)),
        stored_unit("y/1", change="y", needs=("x/4",)),
    )

    removed = store.remove_swept({"x/3": (), "x/4": ()})

    assert removed == []
    assert store.get("x/4").depends_on == ("x/3",)


def test_a_reference_is_never_repointed_to_the_unit_that_holds_it(tmp_path: Path) -> None:
    store = store_of(
        tmp_path,
        stored_unit("x/3", change="x", groups=(3,), state=UNPLANNED),
        stored_unit("x/4", change="x", groups=(3,), needs=("x/3",)),
        stored_unit("x/5", change="x", groups=(3,), needs=("x/3",)),
    )

    store.remove_swept({"x/3": ("x/4",)})

    assert store.get("x/4").needs == ()
    assert store.get("x/5").needs == ("x/4",)


def test_a_successor_that_is_gone_from_the_store_is_not_written_as_a_reference(
    tmp_path: Path,
) -> None:
    store = store_of(
        tmp_path,
        stored_unit("x/3", change="x", groups=(3,), state=UNPLANNED),
        stored_unit("y/1", change="y", needs=("x/3",)),
    )

    assert store.remove_swept({"x/3": ("x/9",)}) == []
    assert store.get("y/1").needs == ("x/3",)


def test_a_unit_that_gained_work_since_it_was_judged_is_left(tmp_path: Path) -> None:
    store = store_of(
        tmp_path, stored_unit("x/3", change="x", groups=(3,), state=UNPLANNED, branch="spec/x/3")
    )

    assert store.remove_swept({"x/3": ()}) == []


def test_a_sweep_of_one_change_leaves_the_tombstones_of_the_others(tmp_path: Path) -> None:
    seen = ({"state": "unplanned", "at": BEFORE.isoformat()},)
    store = store_of(
        tmp_path,
        stored_unit("x/3", change="x", groups=(3,), state=UNPLANNED, history=seen),
        stored_unit("x/4", change="x", groups=(3,)),
        stored_unit("y/3", change="y", groups=(3,), state=UNPLANNED, history=seen),
        stored_unit("y/4", change="y", groups=(3,)),
    )

    removed = sweep(store, active_changes={"x", "y"}, pass_started=AFTER, only_change="x")

    assert removed == ["x/3"]
    assert "y/3" in {unit.id for unit in store.all()}
