"""A replan keeps the splits a unit is parked on (spec: a-dropped-unit-parked-on-a-split-takes-no-
place): when the plan includes the unit, when it leaves it out, and when it plans it again."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.pipeline.unit_store import KEEP, Cause, UnitStore
from agent_build_kit.pipeline.units import PLANNED, UnitState
from tests.factories import stored_unit


def parked_store(tmp_path: Path) -> UnitStore:
    """`feature/1` parked on `acp` as a run leaves it, after one parking of another kind that
    left `parked_attempts` at 1."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([stored_unit("feature/1", change="feature")])
    store.set_state("feature/1", PLANNED, cause=Cause.SERVICE_UNAVAILABLE)
    store.set_state("feature/1", PLANNED, branch="spec/feature/1", cause=Cause.SPLIT_HELD)
    store.set_parked("feature/1", ["acp"], "abc1234", "e2e-test passed the other groups")
    return store


def parked_fields(store: UnitStore) -> tuple[object, ...]:
    unit = store.get("feature/1")
    return (unit.parked_splits, unit.parked_sha, unit.parked_snapshot, unit.parked_attempts)


KEPT = (["acp"], "abc1234", "e2e-test passed the other groups", 1)


def test_a_replan_that_includes_a_parked_unit_keeps_its_park(tmp_path: Path) -> None:
    store = parked_store(tmp_path)

    store.upsert([stored_unit("feature/1", change="feature")], change="feature")

    assert parked_fields(store) == KEPT


def test_a_replan_that_demotes_a_parked_unit_and_plans_it_again_keeps_its_park(
    tmp_path: Path,
) -> None:
    store = parked_store(tmp_path)
    # A replan now keeps a unit with a branch: record the demotion as an earlier one left it.
    store.set_state("feature/1", UnitState.UNPLANNED, cause=KEEP)
    assert parked_fields(store) == KEPT, "a demotion keeps the park"

    store.upsert([stored_unit("feature/1", change="feature")], change="feature")

    assert store.get("feature/1").state == PLANNED
    assert parked_fields(store) == KEPT
