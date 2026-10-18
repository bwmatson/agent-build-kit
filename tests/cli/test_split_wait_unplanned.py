"""A unit parked on an e2e split that the plan dropped is left alone on release, holds no place,
and `abk status` lists it (spec: a-dropped-unit-parked-on-a-split-takes-no-place)."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import PLANNED, RUNNING, UnitState, in_progress, ready_units
from tests.factories import stored_unit
from tests.parked_split_support import Deliveries, hold, installation, park, store_of

pytestmark = pytest.mark.usefixtures("scripted_engine")


def park_without_cause(store: UnitStore, uid: str) -> None:
    """`uid` parked on `acp` whose latest history entry carries no cause."""
    park(store, uid)
    store.set_state(uid, PLANNED, branch=f"spec/{uid}")


def drop(store: UnitStore, uid: str) -> None:
    """A replan of the unit's change that leaves it out, so it is set `unplanned`."""
    store.upsert([], change=uid.partition("/")[0])


def status(inst: Installation, monkeypatch: pytest.MonkeyPatch, capsys) -> list[str]:
    monkeypatch.setattr(cli, "current_usage", lambda: None)
    capsys.readouterr()
    assert cli.cmd_status(argparse.Namespace(), inst) == 0
    return capsys.readouterr().out.splitlines()


def test_release_leaves_an_unplanned_parked_unit_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inst = installation(tmp_path, acp=False)
    thread = Deliveries(monkeypatch)
    store = store_of(inst)
    park(store)
    drop(store, "feature/1")
    before = store.get("feature/1")

    cli.release_split_held(inst, store)

    after = store.get("feature/1")
    assert thread.delivered == []
    assert after.state == UnitState.UNPLANNED
    assert (after.parked_splits, after.branch, after.history) == (
        ["acp"],
        "spec/feature/1",
        before.history,
    )
    assert not in_progress(after), "it stays uncounted"


def test_a_replan_that_plans_it_again_starts_it_by_the_ordinary_round(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inst = installation(tmp_path, acp=False)
    Deliveries(monkeypatch)
    store = store_of(inst)
    park(store)
    drop(store, "feature/1")
    cli.release_split_held(inst, store)

    store.upsert([stored_unit("feature/1", change="feature")], change="feature")

    planned = store.get("feature/1")
    assert planned.state == PLANNED and planned.parked_splits == ["acp"]
    ready = ready_units(
        store.all(), max_concurrent=5, depth_cap=9, max_units_in_progress=inst.max_units_in_progress
    )
    assert [unit.id for unit in ready] == ["feature/1"], "the round resumes it"
    store.set_state("feature/1", RUNNING)
    assert in_progress(store.get("feature/1")), "and it counts once it is running"


def test_status_leaves_two_parked_units_out_of_the_count_and_the_full_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    inst = installation(tmp_path, project_limits={"max_units_in_progress": 3})
    hold(inst, "acp")
    store = store_of(inst)
    park_without_cause(store, "planned/1")
    park_without_cause(store, "dropped/1")
    drop(store, "dropped/1")
    store.upsert([stored_unit("ready/1", change="ready")])
    store.upsert([stored_unit("run/1", change="run")])
    store.set_state("run/1", RUNNING, branch="spec/run/1")

    lines = status(inst, monkeypatch, capsys)

    assert not any("queue is full" in line for line in lines)
    parked = [line for line in lines if "acp" in line and "planned/1" in line]
    dropped = [line for line in lines if "acp" in line and "dropped/1" in line]
    assert len(parked) == 1 and "the usage window is spent" in parked[0]
    assert len(dropped) == 1 and "unplanned" in dropped[0]
    assert "the usage window is spent" in dropped[0]


def test_status_counts_only_the_units_that_hold_a_place(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    inst = installation(tmp_path, project_limits={"max_units_in_progress": 1})
    store = store_of(inst)
    park_without_cause(store, "planned/1")
    park_without_cause(store, "dropped/1")
    drop(store, "dropped/1")
    store.upsert([stored_unit("run/1", change="run")])
    store.set_state("run/1", RUNNING, branch="spec/run/1")

    lines = status(inst, monkeypatch, capsys)

    [full] = [line for line in lines if "queue is full" in line]
    assert "1 units in progress" in full


def test_status_says_a_released_unplanned_unit_is_left_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    inst = installation(tmp_path, acp=False)
    store = store_of(inst)
    park_without_cause(store, "dropped/1")
    drop(store, "dropped/1")

    lines = status(inst, monkeypatch, capsys)

    [dropped] = [line for line in lines if "acp" in line and "dropped/1" in line]
    assert "released, left alone: the plan no longer has it" in dropped
