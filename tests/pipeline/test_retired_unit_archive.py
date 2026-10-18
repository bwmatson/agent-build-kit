"""A change archives with a retired unit only once every group that unit carried is built by a
merged or satisfied unit (spec: a-started-unit-keeps-its-groups)."""

from __future__ import annotations

from agent_build_kit.pipeline.archive import is_ready_to_archive
from agent_build_kit.pipeline.units import MERGED, PLANNED, SATISFIED, UnitState
from tests.factories import stored_unit as unit

RETIRED = UnitState.RETIRED


def test_a_change_is_ready_when_the_groups_of_its_retired_unit_are_merged_elsewhere() -> None:
    units = [
        unit("feat/1", change="feat", groups=(1,), state=MERGED),
        unit("feat/2", change="feat", groups=(2, 3), state=RETIRED, branch="spec/feat/2"),
        unit("feat/4", change="feat", groups=(2, 3), state=MERGED),
    ]

    assert is_ready_to_archive("feat", units)


def test_a_group_built_by_a_satisfied_unit_counts_as_built() -> None:
    units = [
        unit("feat/2", change="feat", groups=(2,), state=RETIRED),
        unit("feat/4", change="feat", groups=(2,), state=SATISFIED),
    ]

    assert is_ready_to_archive("feat", units)


def test_a_change_waits_for_a_group_no_finished_unit_carries_until_one_merges() -> None:
    units = [
        unit("feat/1", change="feat", groups=(1,), state=MERGED),
        unit("feat/2", change="feat", groups=(2, 3), state=RETIRED),
        unit("feat/4", change="feat", groups=(2,), state=MERGED),
    ]

    assert not is_ready_to_archive("feat", units), "group 3 is built by no merged unit"

    units.append(unit("feat/5", change="feat", groups=(3,), state=PLANNED))
    assert not is_ready_to_archive("feat", units), "a planned unit has not built it yet"

    units[-1] = unit("feat/5", change="feat", groups=(3,), state=MERGED)
    assert is_ready_to_archive("feat", units)


def test_a_change_with_a_retired_unit_and_a_planned_unit_is_not_ready() -> None:
    units = [
        unit("feat/2", change="feat", groups=(2,), state=RETIRED),
        unit("feat/4", change="feat", groups=(2,), state=MERGED),
        unit("feat/5", change="feat", groups=(5,), state=PLANNED),
    ]

    assert not is_ready_to_archive("feat", units)

    units[-1] = unit("feat/5", change="feat", groups=(5,), state=MERGED)
    assert is_ready_to_archive("feat", units)
