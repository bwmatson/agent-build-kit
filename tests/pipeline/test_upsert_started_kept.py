"""A replan keeps a planned unit that has work but is not in the plan, and demotes only one that
never started (spec: a-started-unit-keeps-its-groups)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import PLANNED, UnitState
from tests.factories import stored_unit


def with_branch(store: UnitStore, unit_id: str) -> None:
    store.set_state(unit_id, PLANNED, branch=f"spec/{unit_id}")


def with_pull_request(store: UnitStore, unit_id: str) -> None:
    store.set_state(unit_id, PLANNED, pr=7)


def with_pushed_commit(store: UnitStore, unit_id: str) -> None:
    store.record_push(unit_id, "abc1234")


def with_approval(store: UnitStore, unit_id: str) -> None:
    store.record_approval(unit_id, "abc1234")


@pytest.mark.parametrize(
    "start",
    [with_branch, with_pull_request, with_pushed_commit, with_approval],
    ids=["branch", "pull-request", "pushed-commit", "approval"],
)
def test_a_planned_unit_with_work_stays_planned_when_the_plan_omits_it(
    tmp_path: Path, start: Callable[[UnitStore, str], None]
) -> None:
    store = UnitStore(tmp_path / "units.json")
    store.upsert(
        [
            stored_unit("feature/1", change="feature", groups=(1,)),
            stored_unit("feature/2", change="feature", groups=(2,)),
            stored_unit("other/1", change="other", groups=(1,)),
            stored_unit("feature/3", change="feature", groups=(3,)),
        ]
    )
    start(store, "feature/1")
    worked = store.get("feature/1")
    other = store.get("other/1")

    store.upsert([stored_unit("feature/3", change="feature", groups=(3,))], change="feature")

    assert store.get("feature/1") == worked, "state, history and work are as they were"
    assert store.get("feature/1").state == UnitState.PLANNED
    assert store.get("feature/2").state == UnitState.UNPLANNED, "never started: dropped"
    assert store.get("other/1") == other, "another change's unit is not touched"
