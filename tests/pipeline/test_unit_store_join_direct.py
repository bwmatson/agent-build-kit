"""Whatever writes a unit's dependencies stores its direct dependencies.

The repointing of a join stores each dependent's list de-duplicated and reduced. A store
seeded with lists that are not reduced (as one from before the rule is) is read as it is,
so each writer is checked against `direct_dependencies` over everything it left.
"""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import Join, direct_dependencies
from tests.factories import stored_unit, unit

KINDS = ["unit-test"]


def seeded(path: Path, *units) -> UnitStore:
    store = UnitStore(path)
    store.import_units(list(units))
    return store


def assert_stores_direct_dependencies(store: UnitStore) -> None:
    everything = store.all()
    for stored in everything:
        assert stored.depends_on == direct_dependencies(stored, everything), stored.id


def test_a_dependent_listing_the_unit_taken_in_and_the_unit_joined_onto_lists_the_one(
    tmp_path: Path,
) -> None:
    store = seeded(
        tmp_path / "units.json",
        stored_unit("feature/1"),
        stored_unit("feature/2", depends_on=("feature/1",)),
        stored_unit("feature/3", depends_on=("feature/2", "feature/1")),
    )

    assert store.join(Join(onto="feature/1", unit="feature/2"), group_kinds=KINDS) is not None

    assert store.get("feature/3").depends_on == ("feature/1",)
    assert_stores_direct_dependencies(store)


def test_a_repointed_list_drops_a_dependency_another_of_its_dependencies_reaches(
    tmp_path: Path,
) -> None:
    store = seeded(
        tmp_path / "units.json",
        stored_unit("feature/1"),
        stored_unit("feature/2", depends_on=("feature/1",)),
        stored_unit("feature/3", depends_on=("feature/2",)),
        stored_unit("feature/4", depends_on=("feature/2", "feature/3")),
    )

    store.join(Join(onto="feature/1", unit="feature/2"), group_kinds=KINDS)

    assert store.get("feature/4").depends_on == ("feature/3",)


def test_a_join_leaves_every_stored_list_direct(tmp_path: Path) -> None:
    store = seeded(
        tmp_path / "units.json",
        stored_unit("feature/1"),
        stored_unit("feature/2", depends_on=("feature/1",)),
        stored_unit("feature/3", depends_on=("feature/2", "feature/1")),
    )

    store.join(Join(onto="feature/1", unit="feature/2"), group_kinds=KINDS)

    assert_stores_direct_dependencies(store)


def test_an_upsert_leaves_every_stored_list_direct(tmp_path: Path) -> None:
    store = UnitStore(tmp_path / "units.json")

    store.upsert(
        [
            unit("feature/1"),
            unit("feature/2", depends_on=("feature/1",)),
            unit("feature/3", depends_on=("feature/1", "feature/2")),
        ]
    )

    assert_stores_direct_dependencies(store)


def test_set_dependencies_leaves_every_stored_list_direct(tmp_path: Path) -> None:
    store = seeded(
        tmp_path / "units.json",
        stored_unit("feature/1"),
        stored_unit("feature/2", depends_on=("feature/1",)),
        stored_unit("feature/3"),
    )

    store.set_dependencies("feature/3", ("feature/1", "feature/2"))

    assert_stores_direct_dependencies(store)
