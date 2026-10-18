"""A join deletes the unit it takes in and repoints every field that names it, in the same
write (spec: a-replaced-unit-points-to-its-successor)."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import Join, UnitState
from tests.factories import stored_unit


def test_a_join_repoints_depends_on_needs_waited_on_and_superseded_by_once_each(
    tmp_path: Path,
) -> None:
    writes: list[int] = []
    store = UnitStore(tmp_path / "units.json", on_write=lambda units: writes.append(len(units)))
    store.import_units(
        [
            stored_unit("a/1", change="a", groups=(1,)),
            stored_unit("b/1", change="b", groups=(1,)),
            stored_unit(
                "c/1",
                change="c",
                state=UnitState.RUNNING,
                depends_on=("b/1", "a/1", "z/1"),
                needs=("b/1", "z/1"),
                waited_on=("z/1", "b/1"),
            ),
            stored_unit("d/1", change="d", state=UnitState.UNPLANNED, superseded_by=("b/1", "e/1")),
            stored_unit("e/1", change="e", depends_on=("z/1",), needs=("z/1",)),
        ]
    )
    before = len(writes)

    assert store.join(Join(onto="a/1", unit="b/1"), group_kinds=()) is not None

    assert len(writes) - before == 1, "one write"
    assert [u.id for u in store.all() if u.id == "b/1"] == []
    running = store.get("c/1")
    assert running.depends_on == ("a/1", "z/1")
    assert running.needs == ("a/1", "z/1")
    assert running.waited_on == ("z/1", "a/1")
    assert store.get("d/1").superseded_by == ("a/1", "e/1")
    untouched = store.get("e/1")
    assert (untouched.depends_on, untouched.needs) == (("z/1",), ("z/1",))
