"""What the restack lane owes a unit is the same after a replan as before it."""

from __future__ import annotations

import pytest

from agent_build_kit.pipeline.restack_lane import owed_a_moved_base_run, owed_a_restack
from agent_build_kit.pipeline.unit_store import Cause, StoredUnit, UnitStore
from agent_build_kit.pipeline.units import PLANNED
from tests.factories import unit
from tests.standing_causes import REPLANS, replan

CHANGE = "add-marker"
UNIT = "add-marker/1"
OWED = {
    Cause.BASE_CHANGED: True,
    Cause.RESTACK_DEFERRED: True,
    Cause.RESTACK_CONFLICT: False,
    Cause.RESTACK_HANDED_BACK: False,
}


def answers(store: UnitStore) -> tuple[bool, bool]:
    stored: StoredUnit = store.get(UNIT)
    graph = store.all()
    return (
        owed_a_restack(
            stored,
            graph,
            holds_base=lambda unit: False,
            held=lambda unit: False,
            leased=lambda unit: False,
        ),
        owed_a_moved_base_run(
            stored,
            graph,
            has_commits=lambda unit: True,
            head=lambda unit: "",
            held=lambda unit: False,
            leased=lambda unit: False,
        ),
    )


@pytest.mark.parametrize("how", REPLANS)
@pytest.mark.parametrize("cause", list(OWED))
def test_the_lane_owes_a_unit_what_it_owed_it_before_a_replan(
    tmp_path, cause: Cause, how: str
) -> None:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit(UNIT)], change=CHANGE)
    store.set_state(UNIT, PLANNED, branch=f"spec/{UNIT}", cause=cause)
    before = answers(store)
    assert before == (OWED[cause], True)

    replan(store, how, [unit(UNIT)], change=CHANGE)

    assert store.get(UNIT).state == PLANNED
    assert answers(store) == before
