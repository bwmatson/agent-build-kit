"""The predecessor a thread is told it moves onto is the unit the base names, whatever order the
unit's dependencies are listed in.

`predecessor` took the last same-repo parent listed when the base was the trunk, and the
base took the last in-review one listed; a started unit now chooses both as an unstarted one
does.
"""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import (
    IN_REVIEW,
    MERGED,
    RUNNING,
    SATISFIED,
    UnitState,
    base_of,
)
from agent_build_kit.pipeline.wiring import predecessor
from tests.factories import stored_unit as unit

ORDERS = [("feature/1", "feature/2"), ("feature/2", "feature/1")]


def store_of(tmp_path: Path, units, states: dict[str, UnitState]) -> UnitStore:
    """Units stored as listed (a store from before dependencies were reduced), each in its
    state with a branch, and `feature/9` started."""
    store = UnitStore(tmp_path / "units.json")
    store.import_units(units)
    for uid, state in states.items():
        store.set_state(uid, state, pr=int(uid.rsplit("/", 1)[1]), branch=f"spec/{uid}")
    return store


def predecessor_of_started(store: UnitStore) -> str:
    started = store.get("feature/9")
    named = predecessor(started, base_of(started, store.all()), store)
    assert named is not None
    return named.id


def test_predecessor_is_the_base_unit_for_both_orders_of_a_list(tmp_path: Path) -> None:
    named = {}
    for order in ORDERS:
        store = store_of(
            tmp_path / "-".join(p.rsplit("/", 1)[1] for p in order),
            [
                unit("feature/1", change="feature"),
                unit("feature/2", change="feature", depends_on=("feature/1",)),
                unit("feature/9", change="feature", depends_on=order),
            ],
            {"feature/1": IN_REVIEW, "feature/2": IN_REVIEW, "feature/9": RUNNING},
        )
        assert base_of(store.get("feature/9"), store.all()) == "spec/feature/2"
        named[order] = predecessor_of_started(store)

    assert set(named.values()) == {"feature/2"}


def test_predecessor_is_the_same_unit_for_both_orders_when_the_parents_merged(
    tmp_path: Path,
) -> None:
    named = set()
    for order in ORDERS:
        store = store_of(
            tmp_path / "-".join(p.rsplit("/", 1)[1] for p in order),
            [
                unit("feature/1", change="feature"),
                unit("feature/2", change="feature", depends_on=("feature/1",)),
                unit("feature/9", change="feature", depends_on=order),
            ],
            {"feature/1": MERGED, "feature/2": MERGED, "feature/9": RUNNING},
        )
        assert base_of(store.get("feature/9"), store.all()) == "main"
        named.add(predecessor_of_started(store))

    assert named == {"feature/2"}


def test_predecessor_is_the_parent_a_satisfied_unit_was_built_on(tmp_path: Path) -> None:
    """feature/3 is satisfied and was built on feature/2, which is built on feature/1."""
    named = set()
    for order in (("feature/3", "feature/1"), ("feature/1", "feature/3")):
        store = store_of(
            tmp_path / "-".join(p.rsplit("/", 1)[1] for p in order),
            [
                unit("feature/1", change="feature"),
                unit("feature/2", change="feature", depends_on=("feature/1",)),
                unit("feature/3", change="feature", depends_on=("feature/2",)),
                unit("feature/9", change="feature", depends_on=order),
            ],
            {
                "feature/1": IN_REVIEW,
                "feature/2": IN_REVIEW,
                "feature/3": SATISFIED,
                "feature/9": RUNNING,
            },
        )
        named.add(predecessor_of_started(store))

    assert named == {"feature/2"}
