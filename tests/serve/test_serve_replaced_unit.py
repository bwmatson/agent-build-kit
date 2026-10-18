"""The graph data gives a replaced unit its successors and a dependent its resolved
dependencies (spec: a-replaced-unit-points-to-its-successor)."""

from __future__ import annotations

import httpx

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import UnitState
from tests.factories import stored_unit


def test_the_unit_summary_lists_replaced_by_and_a_dependent_lists_the_successor(
    inst: Installation, api: httpx.Client
) -> None:
    UnitStore(inst.state_dir / "units.json").import_units(
        [
            stored_unit("x/3", change="x", state=UnitState.UNPLANNED, superseded_by=("x/5",)),
            stored_unit("x/5", change="x"),
            stored_unit("d/1", change="d", depends_on=("x/3",)),
        ]
    )

    listed = {item["id"]: item for item in api.get("/api/pipeline").json()["units"]}
    dependent = api.get("/api/units/d/1").json()

    assert listed["x/3"]["replaced_by"] == ["x/5"]
    assert [item["id"] for item in dependent["depends_on"]] == ["x/5"]
