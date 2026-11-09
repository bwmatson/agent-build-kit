"""The flag that a moved-base run is the lane's, and the cause of a unit handed back
(spec: unit-scheduling)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_build_kit.pipeline.unit_store import Cause, UnitStore
from agent_build_kit.pipeline.units import HELD, IN_REVIEW, PLANNED, RUNNING, UnitState
from tests.factories import unit as new_unit
from tests.tick_pass import isolate

UNIT = "add-marker/1"
WAIT = 30
SEVERAL_REFRESHES = 5

pytestmark = pytest.mark.usefixtures("scripted_engine")


@pytest.fixture(autouse=True)
def isolated(monkeypatch: pytest.MonkeyPatch) -> None:
    isolate(monkeypatch)


def record(store: UnitStore) -> dict:
    return json.loads(store.path.read_text())["units"][0]


def flagged(tmp_path: Path) -> UnitStore:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([new_unit(UNIT)])
    store.set_state(UNIT, RUNNING, branch="spec/add-marker/1")
    store.set_moved_base_run(UNIT, True)
    return store


def test_a_record_stored_without_the_flag_reads_false_and_is_written_back_with_it(
    tmp_path: Path,
) -> None:
    store = flagged(tmp_path)
    raw = json.loads(store.path.read_text())
    del raw["units"][0]["moved_base_run"]
    store.path.write_text(json.dumps(raw))

    assert UnitStore(store.path).get(UNIT).moved_base_run is False

    UnitStore(store.path).set_feedback(UNIT, "x")

    assert record(store)["moved_base_run"] is False


def test_the_flag_is_kept_by_the_stores_other_writes(tmp_path: Path) -> None:
    store = flagged(tmp_path)

    store.set_feedback(UNIT, "x")
    store.record_step(UNIT, "prepare")

    assert UnitStore(store.path).get(UNIT).moved_base_run is True


@pytest.mark.parametrize("state", [PLANNED, IN_REVIEW, HELD])
def test_a_state_change_out_of_running_clears_the_flag(tmp_path: Path, state: UnitState) -> None:
    store = flagged(tmp_path)

    store.set_state(UNIT, state, note="out")

    assert UnitStore(store.path).get(UNIT).moved_base_run is False


def test_the_lane_clears_the_flag_when_it_hands_the_unit_back(tmp_path: Path) -> None:
    store = flagged(tmp_path)

    store.set_moved_base_run(UNIT, False)

    assert UnitStore(store.path).get(UNIT).moved_base_run is False


def test_the_cause_of_a_unit_handed_back_round_trips_through_the_store(tmp_path: Path) -> None:
    store = flagged(tmp_path)

    store.set_state(UNIT, PLANNED, cause=Cause.RESTACK_HANDED_BACK)

    assert Cause.RESTACK_HANDED_BACK.value == "restack_handed_back"
    assert UnitStore(store.path).get(UNIT).cause is Cause.RESTACK_HANDED_BACK


def test_a_replan_keeps_the_flag_of_a_running_unit(tmp_path: Path) -> None:
    store = flagged(tmp_path)

    store.upsert([new_unit(UNIT)])

    kept = UnitStore(store.path).get(UNIT)
    assert kept.moved_base_run is True
    assert kept.state == RUNNING
