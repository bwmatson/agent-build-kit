"""A store written before the merge gate was removed still loads, and loses the key.

Every record an earlier version wrote carries `merge_before`, usually empty. The
store is the source of truth, so refusing to read it would stop every tick.
"""

import json

import pytest

from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import IN_REVIEW, waiting_on
from tests.factories import unit


def with_old_gate(path, uid: str, gate: list[str]) -> None:
    """What an earlier version left on disk: the key beside the record."""
    raw = json.loads(path.read_text())
    records = raw["units"].values() if isinstance(raw["units"], dict) else raw["units"]
    for record in records:
        if record["id"] == uid:
            record["merge_before"] = gate
    path.write_text(json.dumps(raw))


@pytest.mark.parametrize("gate", [[], ["add-marker/1"]])
def test_a_store_carrying_merge_before_loads_and_the_next_write_drops_the_key(
    tmp_path, gate: list[str]
) -> None:
    path = tmp_path / "units.json"
    store = UnitStore(path)
    store.upsert([unit("add-marker/1"), unit("add-marker/2", depends_on=("add-marker/1",))])
    with_old_gate(path, "add-marker/2", gate)

    loaded = UnitStore(path).get("add-marker/2")
    UnitStore(path).set_state("add-marker/1", IN_REVIEW, pr=4)

    assert loaded.depends_on == ("add-marker/1",)
    assert "merge_before" not in path.read_text()


def test_a_unit_with_a_stored_gate_waits_on_its_dependency_alone(tmp_path) -> None:
    path = tmp_path / "units.json"
    store = UnitStore(path)
    store.upsert([unit("add-marker/1"), unit("add-marker/2", depends_on=("add-marker/1",))])
    store.set_state("add-marker/1", IN_REVIEW, branch="spec/add-marker/1", pr=4)
    with_old_gate(path, "add-marker/2", ["add-marker/1"])

    reloaded = UnitStore(path)

    assert waiting_on(reloaded.get("add-marker/2"), reloaded.all()) == []
