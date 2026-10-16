"""A unit's test kind in the store and in a plan: either spelling is read as a `TestTier`,
and only the new spelling is written."""

import json

import pytest

from agent_build_kit.model import TestTier
from agent_build_kit.pipeline.planner import parse_graph
from agent_build_kit.pipeline.unit_store import UnitStore
from tests.factories import unit

UNIT_ID = "add-marker/1"
OLD_TO_NEW = {"tier1": TestTier.UNIT_TEST, "tier2": TestTier.E2E_TEST}


def records(store: UnitStore) -> list[dict]:
    return json.loads(store.path.read_text())["units"]


def stored_with(tmp_path, kind: str) -> UnitStore:
    """A store whose one unit was written with `kind` as its recorded `tier`."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit(UNIT_ID)])
    raw = json.loads(store.path.read_text())
    raw["units"][0]["tier"] = kind
    store.path.write_text(json.dumps(raw))
    return store


def plan_with(kind: str) -> str:
    unit_record = {"id": UNIT_ID, "change": "add-marker", "title": "t", "repo": "app", "tier": kind}
    return json.dumps({"units": [unit_record]})


@pytest.mark.parametrize("old", sorted(OLD_TO_NEW))
def test_a_store_written_before_the_rename_reads_the_kind_as_a_test_tier(tmp_path, old) -> None:
    store = stored_with(tmp_path, old)

    assert store.get(UNIT_ID).tier is OLD_TO_NEW[old]


@pytest.mark.parametrize("old", sorted(OLD_TO_NEW))
def test_the_next_write_holds_only_the_new_value(tmp_path, old) -> None:
    store = stored_with(tmp_path, old)

    store.set_run_log(UNIT_ID, "run.log")

    assert records(store)[0]["tier"] == OLD_TO_NEW[old].value
    assert old not in store.path.read_text()


@pytest.mark.parametrize("kind", list(TestTier))
def test_a_new_value_is_read_back_as_the_same_test_tier(tmp_path, kind) -> None:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit(UNIT_ID, tier=kind.value)])

    assert UnitStore(store.path).get(UNIT_ID).tier is kind
    assert records(store)[0]["tier"] == kind.value


@pytest.mark.parametrize("old", sorted(OLD_TO_NEW))
def test_a_plan_written_before_the_rename_reads_the_kind_as_a_test_tier(old) -> None:
    assert parse_graph(plan_with(old))[0].tier is OLD_TO_NEW[old]


@pytest.mark.parametrize("kind", list(TestTier))
def test_a_plan_with_the_new_values_reads_them(kind) -> None:
    assert parse_graph(plan_with(kind.value))[0].tier is kind


def test_a_stored_unit_with_an_unknown_kind_is_refused(tmp_path) -> None:
    store = stored_with(tmp_path, "integration")

    with pytest.raises(ValueError, match="units.json"):
        store.all()
