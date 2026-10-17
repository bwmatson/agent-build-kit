"""The flag that a moved-base run is the lane's, and the cause of a unit handed back
(spec: unit-scheduling)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline.unit_store import Cause, UnitStore
from agent_build_kit.pipeline.units import HELD, IN_REVIEW, PLANNED, RUNNING, UnitState
from tests.factories import unit as new_unit
from tests.tick_driver import count_refreshes
from tests.tick_pass import Builder, install_builder, isolate, stored, tick, workspace
from tests.waiting import wait_for

UNIT = "add-marker/1"
WAIT = 30
SEVERAL_REFRESHES = 5

pytestmark = pytest.mark.usefixtures("scripted_engine")


@pytest.fixture(autouse=True)
def isolated(monkeypatch: pytest.MonkeyPatch) -> None:
    isolate(monkeypatch)
    monkeypatch.setattr(cli, "REFRESH_SECONDS", 0.05)


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


def test_a_running_pass_lets_a_handed_back_unit_in_and_still_refuses_the_causes_it_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    builder: Builder = install_builder(tmp_path, monkeypatch)
    inst = workspace(tmp_path, max_concurrent=3)
    builder.store.upsert([stored("back/1"), stored("usage/1"), stored("slow/1", repo="platform")])
    refreshes = count_refreshes(monkeypatch)
    runs: list[int] = []

    def held_once() -> str | None:
        runs.append(1)
        return "held" if len(runs) == 1 else None

    builder.scripts["back/1"] = held_once
    builder.ends["back/1"] = (PLANNED, Cause.RESTACK_HANDED_BACK, "handed back")
    builder.ends["usage/1"] = (PLANNED, Cause.USAGE, "usage")
    builder.scripts["usage/1"] = lambda: "held"

    def slow() -> str | None:
        wait_for(
            lambda: builder.started.count("back/1") == 2,
            what="back/1 to be started a second time",
            timeout=WAIT,
        )
        refreshes.wait_for(refreshes.count + SEVERAL_REFRESHES, timeout=WAIT)
        return None

    builder.scripts["slow/1"] = slow

    assert tick(inst) == 0

    assert builder.started.count("back/1") == 2
    assert builder.started.count("usage/1") == 1
