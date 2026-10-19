"""The unit route lists a unit's direct dependencies, the same ones the other views name."""

from __future__ import annotations

from pathlib import Path

import httpx

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import direct_dependencies
from tests.factories import stored_unit

RECORDED = Path(__file__).parent.parent / "fixtures" / "stores" / "recorded_units.json"


def test_the_dependencies_list_names_the_direct_ones_in_the_stored_order(
    inst: Installation, api: httpx.Client
) -> None:
    UnitStore(inst.state_dir / "units.json").import_units(
        [
            stored_unit("e/1", change="e", state="merged"),
            stored_unit("a/1", change="a", state="merged"),
            stored_unit("a/2", change="a", state="failed", depends_on=("a/1",)),
            stored_unit("a/3", change="a", depends_on=("e/1", "a/1", "a/2")),
        ]
    )

    listed = api.get("/api/units/a/3").json()["depends_on"]

    assert listed == [{"id": "e/1", "status": "merged"}, {"id": "a/2", "status": "failed"}]
    assert api.get("/api/units/e/1").json()["depends_on"] == []


def test_the_page_of_every_recorded_unit_names_its_direct_dependencies(
    inst: Installation, api: httpx.Client
) -> None:
    store = UnitStore(inst.state_dir / "units.json")
    store.import_units(UnitStore(RECORDED).all())
    units = store.all()

    for unit in units:
        listed = api.get(f"/api/units/{unit.id}").json()["depends_on"]
        assert [item["id"] for item in listed] == list(direct_dependencies(unit, units)), unit.id
