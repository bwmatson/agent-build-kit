"""Nothing carries a unit from the old engine: a units store that still holds its
fields does not load, and no code converts them."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline.unit_store import StoredUnit, UnitStore
from agent_build_kit.pipeline.units import PLANNED
from tests.factories import unit

IN_RUN_FIELDS = ["review_rounds", "deferred", "pending_replies", "person_comments"]
OLD_VALUES: list[tuple[str, object]] = [
    *[(field, ["x"]) for field in IN_RUN_FIELDS],
    ("resume_from", "review"),
    ("classic_run", {"review_rounds": [1]}),
]


def _store_with(tmp_path: Path, **fields: object) -> UnitStore:
    """A store holding `a/1` and `a/2`, with `fields` written onto `a/2`'s record."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit("a/1"), unit("a/2")])
    raw = json.loads(store.path.read_text())
    raw["units"][1].update(fields)
    store.path.write_text(json.dumps(raw))
    return store


@pytest.mark.parametrize(("field", "value"), OLD_VALUES)
def test_a_store_with_an_old_engine_field_fails_naming_the_unit_and_the_field(
    tmp_path: Path, field: str, value: object
) -> None:
    store = _store_with(tmp_path, **{field: value})

    with pytest.raises(ValueError) as error:
        store.all()

    assert "a/2" in str(error.value)
    assert field in str(error.value)


@pytest.mark.parametrize("field", IN_RUN_FIELDS)
def test_an_empty_in_run_key_is_refused_too(tmp_path: Path, field: str) -> None:
    store = _store_with(tmp_path, **{field: []})

    with pytest.raises(ValueError, match=field):
        store.all()


def test_a_store_as_the_previous_release_wrote_it_loads_and_is_rewritten_without_the_keys(
    tmp_path: Path,
) -> None:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit("a/1"), unit("a/2")])
    raw = json.loads(store.path.read_text())
    for record in raw["units"]:
        record["resume_from"] = ""
        record["classic_run"] = {}
    store.path.write_text(json.dumps(raw))

    assert [stored.id for stored in store.all()] == ["a/1", "a/2"]

    store.set_state("a/2", PLANNED, note="requeued", branch="spec/a/2")

    for record in json.loads(store.path.read_text())["units"]:
        assert "resume_from" not in record
        assert "classic_run" not in record


def test_the_error_tells_the_operator_to_finish_or_requeue_the_old_work(tmp_path: Path) -> None:
    store = _store_with(tmp_path, review_rounds=[{"n": 1}])

    with pytest.raises(ValueError) as error:
        store.all()

    assert "requeue" in str(error.value)


def test_a_current_store_loads(tmp_path: Path) -> None:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit("a/1"), unit("a/2")])
    store.set_state("a/2", PLANNED, note="requeued", branch="spec/a/2")

    assert [stored.id for stored in store.all()] == ["a/1", "a/2"]


def test_no_module_converts_units_from_the_old_engine() -> None:
    assert importlib.util.find_spec("agent_build_kit.graph.convert") is None
    assert not hasattr(cli, "convert_in_flight")


def test_the_unit_store_keeps_no_old_engine_field() -> None:
    assert "resume_from" not in StoredUnit.model_fields
    assert "classic_run" not in StoredUnit.model_fields
    assert not hasattr(UnitStore, "clear_converted")
