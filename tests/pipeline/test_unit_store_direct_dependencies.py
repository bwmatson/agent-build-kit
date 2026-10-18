"""The store writes a unit's direct dependencies, whichever way they arrive.

`upsert` takes them from the plan, `set_dependencies` from a caller; both store the
reduced list, and the rest of the record is as it was.
"""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import FAILED, MERGED
from tests.factories import unit


def test_a_plan_depending_on_a_parent_and_its_parent_stores_the_parent_alone(
    tmp_path: Path,
) -> None:
    store = UnitStore(tmp_path / "units.json")

    store.upsert(
        [
            unit("feature/1"),
            unit("feature/2", depends_on=("feature/1",)),
            unit("feature/3", depends_on=("feature/2", "feature/1")),
        ]
    )

    assert store.get("feature/3").depends_on == ("feature/2",)


def test_a_grandparent_stored_but_not_in_the_plan_is_reduced_away(tmp_path: Path) -> None:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit("old/1", change="old"), unit("old/2", change="old", depends_on=("old/1",))])
    store.set_state("old/2", MERGED)

    store.upsert([unit("feature/1", depends_on=("old/2", "old/1"))], change="feature")

    assert store.get("feature/1").depends_on == ("old/2",)


def test_set_dependencies_stores_the_reduced_list_and_touches_nothing_else(
    tmp_path: Path,
) -> None:
    store = UnitStore(tmp_path / "units.json")
    store.upsert(
        [
            unit("feature/1"),
            unit("feature/2", depends_on=("feature/1",)),
            unit("feature/3", estimated_lines=123),
        ]
    )
    before = store.get("feature/3")

    store.set_dependencies("feature/3", ("feature/2", "feature/1"))

    after = store.get("feature/3")
    assert after.depends_on == ("feature/2",)
    assert after == before.model_copy(update=dict(depends_on=("feature/2",)))


def test_a_started_unit_keeps_the_dependencies_the_plan_did_not_change(tmp_path: Path) -> None:
    store = UnitStore(tmp_path / "units.json")
    store.upsert(
        [
            unit("feature/1"),
            unit("feature/2", depends_on=("feature/1",)),
            unit("feature/3"),
            unit("feature/4", depends_on=("feature/2", "feature/3")),
        ]
    )
    store.set_state("feature/4", FAILED, branch="spec/feature/4")

    store.upsert(
        [
            unit("feature/1"),
            unit("feature/2", depends_on=("feature/1",)),
            unit("feature/3"),
            unit("feature/4", depends_on=("feature/2", "feature/1", "feature/3")),
        ]
    )

    assert store.get("feature/4").depends_on == ("feature/2", "feature/3")


def test_the_record_read_back_is_the_record_written(tmp_path: Path) -> None:
    path = tmp_path / "units.json"
    store = UnitStore(path)
    store.upsert(
        [
            unit("feature/1"),
            unit("feature/2", depends_on=("feature/1",)),
            unit("feature/3", depends_on=("feature/2", "feature/1")),
        ]
    )

    assert UnitStore(path).get("feature/3") == store.get("feature/3")
    assert UnitStore(path).get("feature/3").depends_on == ("feature/2",)
