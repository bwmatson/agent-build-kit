"""`UnitStore.retire` records the end of a unit as one write: the state, the cause, the reason and
the command that did it, and no person (spec: a-started-unit-keeps-its-groups)."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.pipeline.unit_store import Cause, StoredUnit, UnitStore
from agent_build_kit.pipeline.units import UnitState
from tests.factories import stored_unit


def store_with_unit(tmp_path: Path, writes: list[int]) -> UnitStore:
    store = UnitStore(tmp_path / "units.json", on_write=lambda units: writes.append(len(units)))
    store.upsert([stored_unit("app/3", change="app", groups=(16,))])
    store.set_state("app/3", UnitState.PLANNED, branch="spec/app/3")
    return store


def test_retire_writes_the_state_cause_reason_and_command_in_one_write(tmp_path: Path) -> None:
    writes: list[int] = []
    store = store_with_unit(tmp_path, writes)
    before = len(writes)

    store.retire("app/3", "built in app/4")

    assert len(writes) - before == 1, "one write"
    unit: StoredUnit = store.get("app/3")
    assert unit.state == UnitState.RETIRED
    assert unit.cause == Cause.RETIRED
    assert unit.branch == "spec/app/3", "the branch is kept"
    entry = unit.history[-1]
    assert entry["state"] == "retired"
    assert entry["cause"] == "retired"
    assert entry["note"] == "built in app/4"
    assert entry["by"] == "abk retire"
    assert set(entry) == {"state", "at", "cause", "note", "by"}, "no user name"


def test_retire_without_a_reason_still_says_what_happened(tmp_path: Path) -> None:
    store = store_with_unit(tmp_path, [])

    store.retire("app/3")

    entry = store.get("app/3").history[-1]
    assert (entry["state"], entry["cause"], entry["by"]) == ("retired", "retired", "abk retire")
    assert entry["note"] == "retired"
