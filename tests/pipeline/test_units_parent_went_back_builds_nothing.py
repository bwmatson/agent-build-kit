"""A parent that now builds nothing does not make a returning unit wait for room.

A planned unit with work and no pull request whose parent was outside review since the
unit last changed waits for room like a new unit. A parent that is now `unplanned` or
`retired` is skipped, whatever its history says, as `waiting_on` skips it. (A live parent
whose history holds a state outside review still does: see `test_blocked_units.py`.)
"""

from __future__ import annotations

import pytest

from agent_build_kit.pipeline.units import IN_REVIEW, UnitState, ready_units
from tests.factories import new_unit as new
from tests.factories import worked_unit as worked


def entry(state: str, hour: int) -> dict:
    return {"state": state, "at": f"2026-09-23T{hour:02d}:00:00+00:00"}


def chosen(graph, *, limit: int) -> list[str]:
    return [
        unit.id
        for unit in ready_units(graph, max_concurrent=9, depth_cap=9, max_units_in_progress=limit)
    ]


@pytest.mark.parametrize("state", [UnitState.UNPLANNED, UnitState.RETIRED])
def test_a_parent_now_dropped_does_not_make_a_paused_unit_wait_for_room(
    state: UnitState,
) -> None:
    graph = [
        new("busy/1", state=IN_REVIEW, pr=1),
        new("busy/2", state=IN_REVIEW, pr=2),
        new(
            "p/1",
            state=state,
            history=(entry("in_review", 8), entry("planned", 11), entry(state, 12)),
        ),
        worked("back/1", depends_on=("p/1",), history=(entry("planned", 10),)),
    ]

    assert chosen(graph, limit=2) == ["back/1"]
