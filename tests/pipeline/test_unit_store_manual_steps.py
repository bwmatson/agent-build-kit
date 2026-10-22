"""A unit's manual steps in the store (spec: manual-steps).

A record written before manual steps existed loads with none, and a re-plan keeps the steps a
builder raised beside the ones the plan declares.
"""

import json

from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import ManualStep
from tests.factories import unit

UNIT_ID = "feature/1"
DECLARED = ManualStep(slug="flip-marker", text="Flip it", runbook="docs/r.md#flip", line=4)
RAISED = ManualStep(slug="pre-commit-config", text="Install it", check=".abk/manual/p.sh")


def test_a_record_written_without_the_field_loads_with_no_steps(tmp_path) -> None:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit(UNIT_ID)])
    raw = json.loads(store.path.read_text())
    for record in raw["units"]:
        record.pop("manual_steps", None)
    store.path.write_text(json.dumps(raw))

    assert UnitStore(store.path).get(UNIT_ID).manual_steps == ()


def test_a_replan_keeps_a_raised_step_beside_the_declared_one(tmp_path) -> None:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit(UNIT_ID)])
    store.set_manual_steps(UNIT_ID, [RAISED])

    store.upsert([unit(UNIT_ID, manual_steps=(DECLARED,))], change="feature")

    assert UnitStore(store.path).get(UNIT_ID).manual_steps == (DECLARED, RAISED)


def test_a_replan_with_no_declared_step_still_keeps_the_raised_one(tmp_path) -> None:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit(UNIT_ID)])
    store.set_manual_steps(UNIT_ID, [RAISED])

    store.upsert([unit(UNIT_ID)], change="feature")
    store.upsert([unit(UNIT_ID)], change="feature")

    assert UnitStore(store.path).get(UNIT_ID).manual_steps == (RAISED,)
