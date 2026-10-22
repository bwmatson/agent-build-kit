"""`UnitStore.supersede` closes a unit held for its size and replaces it in one write
(spec: unit-superseding)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from agent_build_kit.pipeline.unit_store import Cause, HeldBy, StoredUnit, UnitStore
from agent_build_kit.pipeline.units import HELD, PLANNED, SATISFIED, UnitState
from tests.factories import stored_unit, unit

HELD_ID = "app/3"
FIRST, LAST = "app/3-s1", "app/3-s2"


def piece(uid: str, groups: tuple[int, ...], depends_on: tuple[str, ...]):
    return unit(uid, change="app", groups=groups, depends_on=depends_on)


def pieces():
    return [piece(FIRST, (3,), ("app/2",)), piece(LAST, (4,), (FIRST,))]


def store_of(tmp_path: Path, *, writes: list[int] | None = None) -> UnitStore:
    store = UnitStore(
        tmp_path / "units.json",
        on_write=(lambda units: writes.append(len(units))) if writes is not None else None,
    )
    store.import_units(
        [
            stored_unit("app/2", change="app", groups=(2,), state=UnitState.MERGED),
            stored_unit(
                HELD_ID, change="app", groups=(3, 4), depends_on=("app/2",), branch="spec/app/3"
            ),
            stored_unit(
                "app/5",
                change="app",
                groups=(5,),
                depends_on=(HELD_ID,),
                needs=(HELD_ID,),
                waited_on=(HELD_ID,),
            ),
        ]
    )
    store.set_state(
        HELD_ID,
        HELD,
        held_by=HeldBy.SIZE,
        cause=Cause.TOO_BIG_FOR_TIER,
        branch="spec/app/3",
        pr=17,
    )
    return store


def test_the_pieces_are_added_as_planned_units_with_the_dependencies_given(
    tmp_path: Path,
) -> None:
    store = store_of(tmp_path)

    store.supersede(HELD_ID, pieces())

    first, last = store.get(FIRST), store.get(LAST)
    assert (first.state, last.state) == (PLANNED, PLANNED)
    assert first.depends_on == ("app/2",)
    assert last.depends_on == (FIRST,)
    assert (first.groups, last.groups) == ((3,), (4,))


def test_the_old_unit_is_closed_with_the_cause_and_its_pieces_and_keeps_its_branch_and_pr(
    tmp_path: Path,
) -> None:
    store = store_of(tmp_path)

    store.supersede(HELD_ID, pieces())

    old: StoredUnit = store.get(HELD_ID)
    assert old.state == UnitState.CLOSED
    assert old.cause == Cause.SUPERSEDED
    assert old.superseded_by == (FIRST, LAST)
    assert (old.branch, old.pr) == ("spec/app/3", 17)
    assert old.held_by == HeldBy.NONE


def test_a_dependent_is_re_pointed_to_the_last_piece_in_dependency_and_needs(
    tmp_path: Path,
) -> None:
    store = store_of(tmp_path)

    store.supersede(HELD_ID, pieces())

    dependent = store.get("app/5")
    assert dependent.depends_on == (LAST,)
    assert dependent.needs == (LAST,)
    assert dependent.waited_on == (LAST,)


def test_a_unit_that_depended_on_it_through_a_satisfied_unit_is_re_pointed_through_it(
    tmp_path: Path,
) -> None:
    store = store_of(tmp_path)
    store.import_units(
        [
            stored_unit("app/6", change="app", groups=(6,), state=SATISFIED, depends_on=(HELD_ID,)),
            stored_unit("app/7", change="app", groups=(7,), depends_on=("app/6",)),
        ]
    )

    store.supersede(HELD_ID, pieces())

    assert store.get("app/6").depends_on == (LAST,)
    assert store.get("app/7").depends_on == ("app/6",)
    assert all(HELD_ID not in unit.depends_on for unit in store.all())


def test_it_is_one_write(tmp_path: Path) -> None:
    writes: list[int] = []
    store = store_of(tmp_path, writes=writes)
    before = len(writes)

    store.supersede(HELD_ID, pieces())

    assert len(writes) - before == 1


@pytest.mark.skipif(os.geteuid() == 0, reason="a read-only directory does not stop root")
def test_a_failed_write_leaves_the_store_as_it_was(tmp_path: Path) -> None:
    store = store_of(tmp_path)
    before = store.path.read_text()
    tmp_path.chmod(0o500)
    try:
        with pytest.raises(OSError):
            store.supersede(HELD_ID, pieces())
    finally:
        tmp_path.chmod(0o700)

    assert store.path.read_text() == before


def test_a_unit_not_held_by_size_is_refused_and_nothing_changes(tmp_path: Path) -> None:
    store = store_of(tmp_path)
    store.set_state(HELD_ID, HELD, held_by=HeldBy.REVIEW, cause=Cause.NEEDS_HUMAN)
    before = store.path.read_text()

    with pytest.raises(ValueError):
        store.supersede(HELD_ID, pieces())

    assert store.path.read_text() == before
