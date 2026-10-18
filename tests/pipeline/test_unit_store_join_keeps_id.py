"""A join never renumbers the unit it joins onto (spec: unit-ids-come-from-the-groups).

The join is stored, then a replan over the joined groups must give back the id the join kept.
"""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.pipeline.unit_ids import assign_unit_ids
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import Join
from tests.factories import stored_unit, unit


def test_a_join_into_an_unstarted_unit_leaves_its_id_and_the_replan_keeps_it(
    tmp_path: Path,
) -> None:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([stored_unit("y/4", change="y", groups=(4,))])
    join = Join(onto="y/4", change="x", groups=(2,), estimated_lines=30)

    assert store.join(join, group_kinds=["unit-test"]) is not None

    joined = store.get("y/4")
    assert joined is not None and joined.id == "y/4"
    again = assign_unit_ids(
        [unit("u1", change="y", groups=(4,)).model_copy(update={"joined": joined.joined})],
        stored=[joined],
        retired=set(),
        highest_group=4,
    )
    assert [u.id for u in again] == ["y/4"]


def test_a_join_into_a_unit_with_lower_numbered_groups_does_not_renumber_it(
    tmp_path: Path,
) -> None:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([stored_unit("y/6", change="y", groups=(1,))])

    store.join(Join(onto="y/6", change="x", groups=(2,), estimated_lines=30), group_kinds=[])

    joined = store.get("y/6")
    assert joined is not None
    ids = assign_unit_ids(
        [unit("u1", change="y", groups=(1,))],
        stored=[joined],
        retired=set(),
        highest_group=6,
    )
    assert [u.id for u in ids] == ["y/6"] and joined.id == "y/6"
