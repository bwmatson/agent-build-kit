"""`upsert` never revives or reshapes a retired unit, and keeps its record when a plan omits it
(spec: a-started-unit-keeps-its-groups)."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import UnitState
from tests.factories import stored_unit


def store_with_retired(tmp_path: Path, *, branch: str) -> UnitStore:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([stored_unit("app/3", change="app", groups=(16,), title="Old shape")])
    store.set_state("app/3", UnitState.RETIRED, branch=branch)
    return store


def test_a_plan_neither_revives_reshapes_nor_drops_a_retired_unit(tmp_path: Path) -> None:
    store = store_with_retired(tmp_path, branch="spec/app/3")
    before = store.get("app/3")

    store.upsert([stored_unit("app/4", change="app", groups=(17,))], change="app")
    assert store.get("app/3") == before, "a plan that omits it keeps its record"

    store.upsert(
        [
            stored_unit(
                "app/3", change="app", groups=(16, 17), title="New shape", estimated_lines=300
            )
        ],
        change="app",
    )

    assert store.get("app/3") == before
