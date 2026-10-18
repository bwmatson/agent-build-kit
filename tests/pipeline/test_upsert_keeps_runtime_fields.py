"""A replan keeps the runtime fields of a unit it rebuilds: state a run left, not planned shape."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from agent_build_kit.pipeline.unit_store import ClosePending, RequeueReason, UnitStore
from tests.factories import stored_unit, unit

CHANGE = "add-marker"
UNIT = "add-marker/1"
OTHER = "add-marker/2"
STAMP = datetime(2030, 1, 2, 3, 4, 5, tzinfo=UTC)

RUNTIME_FIELDS: dict[str, Any] = {
    "parked_splits": ["acp"],
    "parked_sha": "abc1234",
    "parked_snapshot": "e2e-test passed the other groups",
    "parked_attempts": 3,
    "service_attempts": 2,
    "gated_requeue": RequeueReason.RESUME,
    "waited_on": ("dep/1",),
    "wait_ended": "dep/1 merged",
    "close_pending": ClosePending(pr=7, reason="superseded"),
    "step": "push",
    "guidance": "keep the old marker",
    "ready_at": STAMP,
    "first_human_activity_at": STAMP,
}


# The four a parked unit waits on are carried already; the rest are what this change adds.
UNCARRIED = [
    field
    for field in RUNTIME_FIELDS
    if field not in ("parked_splits", "parked_sha", "parked_snapshot", "parked_attempts")
]


def default_of(field: str) -> Any:
    return getattr(stored_unit("default/1"), field)


@pytest.fixture
def store(tmp_path: Path) -> UnitStore:
    return UnitStore(tmp_path / "units.json")


def with_field(store: UnitStore, field: str) -> None:
    """Both units stored, `UNIT` with `field` set to its value."""
    store.import_units([stored_unit(UNIT, **{field: RUNTIME_FIELDS[field]}), stored_unit(OTHER)])


@pytest.mark.parametrize("field", UNCARRIED)
def test_a_replan_that_includes_the_unit_leaves_the_field_as_it_was(
    store: UnitStore, field: str
) -> None:
    with_field(store, field)

    store.upsert([unit(UNIT), unit(OTHER)], change=CHANGE)

    assert getattr(store.get(UNIT), field) == RUNTIME_FIELDS[field]


@pytest.mark.parametrize("field", UNCARRIED)
def test_a_replan_that_omits_the_unit_and_one_that_includes_it_again_leave_the_field(
    store: UnitStore, field: str
) -> None:
    with_field(store, field)

    store.upsert([unit(OTHER)], change=CHANGE)
    assert getattr(store.get(UNIT), field) == RUNTIME_FIELDS[field]
    store.upsert([unit(UNIT), unit(OTHER)], change=CHANGE)

    assert getattr(store.get(UNIT), field) == RUNTIME_FIELDS[field]


def test_all_thirteen_fields_survive_together_and_a_new_unit_gets_the_defaults(
    store: UnitStore,
) -> None:
    assert len(RUNTIME_FIELDS) == 13
    store.import_units([stored_unit(UNIT, **RUNTIME_FIELDS)])

    store.upsert([unit(OTHER)], change=CHANGE)
    store.upsert([unit(UNIT), unit(OTHER)], change=CHANGE)

    kept = store.get(UNIT)
    assert {field: getattr(kept, field) for field in RUNTIME_FIELDS} == RUNTIME_FIELDS
    fresh = store.get(OTHER)
    assert {field: getattr(fresh, field) for field in RUNTIME_FIELDS} == {
        field: default_of(field) for field in RUNTIME_FIELDS
    }
    assert all(RUNTIME_FIELDS[field] != default_of(field) for field in RUNTIME_FIELDS)


@pytest.mark.parametrize("field", UNCARRIED)
def test_a_record_the_plan_reshapes_keeps_the_field(store: UnitStore, field: str) -> None:
    with_field(store, field)

    store.upsert([unit(UNIT, estimated_lines=300, depends_on=(OTHER,)), unit(OTHER)], change=CHANGE)

    reshaped = store.get(UNIT)
    assert reshaped.estimated_lines == 300
    assert getattr(reshaped, field) == RUNTIME_FIELDS[field]
