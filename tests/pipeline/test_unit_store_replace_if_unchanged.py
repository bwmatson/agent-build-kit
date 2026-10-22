"""`replace_if_unchanged` stores the units a plan made apart changed, and nothing when a unit it
would write has moved since the copy."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import RUNNING
from tests.factories import stored_unit


def seeded(tmp_path: Path) -> UnitStore:
    store = UnitStore(tmp_path / "units.json")
    store.upsert(
        [stored_unit("feature/1", change="feature", groups=(1,))]
        + [stored_unit("other/1", change="other", groups=(1,))]
    )
    return store


def test_an_unchanged_store_takes_the_differing_units_and_no_other(tmp_path: Path) -> None:
    store = seeded(tmp_path)
    base = {unit.id: unit for unit in store.all()}
    store.set_state("other/1", RUNNING, branch="spec/other/1")
    after = {**base, "feature/1": base["feature/1"].model_copy(update={"estimated_lines": 99})}
    after["feature/2"] = base["feature/1"].model_copy(update={"id": "feature/2"})
    base["other/1"] = store.get("other/1")
    after["other/1"] = base["other/1"]
    called: list[str] = []

    moved = store.replace_if_unchanged(base, after, also=lambda: called.append("records"))

    assert moved == []
    assert called == ["records"]
    assert store.get("feature/1").estimated_lines == 99
    assert store.get("feature/2").id == "feature/2"
    assert store.get("other/1").state == RUNNING


def test_a_unit_changed_since_the_copy_is_returned_and_nothing_is_written(
    tmp_path: Path,
) -> None:
    store = seeded(tmp_path)
    base = {unit.id: unit for unit in store.all()}
    after = {**base, "feature/1": base["feature/1"].model_copy(update={"estimated_lines": 99})}
    store.set_state("feature/1", RUNNING, branch="spec/feature/1")
    written = store.path.read_bytes()
    called: list[str] = []

    moved = store.replace_if_unchanged(base, after, also=lambda: called.append("records"))

    assert moved == ["feature/1"]
    assert called == []
    assert store.path.read_bytes() == written


def test_a_unit_added_since_the_copy_is_returned_and_nothing_is_written(tmp_path: Path) -> None:
    store = seeded(tmp_path)
    base = {unit.id: unit for unit in store.all()}
    planned_here = base["feature/1"].model_copy(update={"id": "feature/2"})
    store.upsert([stored_unit("feature/2", change="feature", groups=(2,))])
    written = store.path.read_bytes()

    moved = store.replace_if_unchanged(base, {**base, "feature/2": planned_here})

    assert moved == ["feature/2"]
    assert store.path.read_bytes() == written


def test_a_unit_the_plan_removed_is_removed_from_the_store(tmp_path: Path) -> None:
    store = seeded(tmp_path)
    base = {unit.id: unit for unit in store.all()}
    after = {uid: unit for uid, unit in base.items() if uid != "feature/1"}

    moved = store.replace_if_unchanged(base, after)

    assert moved == []
    assert [unit.id for unit in store.all()] == ["other/1"]


def test_a_removed_unit_that_changed_since_the_copy_is_returned_and_nothing_is_written(
    tmp_path: Path,
) -> None:
    store = seeded(tmp_path)
    base = {unit.id: unit for unit in store.all()}
    after = {uid: unit for uid, unit in base.items() if uid != "feature/1"}
    store.set_state("feature/1", RUNNING, branch="spec/feature/1")
    written = store.path.read_bytes()

    moved = store.replace_if_unchanged(base, after)

    assert moved == ["feature/1"]
    assert store.path.read_bytes() == written
