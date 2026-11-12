"""`abk tick` is a dispatcher (spec: unit-workers): it admits ready
units up to the limits, marks them `starting`, starts one worker for each and exits without waiting
for any; a second dispatcher exits at once; a unit with a usage pause that has not reached its time
is given no worker and still holds its place."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.file_lock import file_lock
from agent_build_kit.pipeline.resolution_lane import lane_held_by_record, write_worker_record
from agent_build_kit.pipeline.unit_store import Cause, Starting
from agent_build_kit.pipeline.units import HELD, IN_REVIEW, RUNNING, project_key
from agent_build_kit.pipeline.usage_guard import Decision
from agent_build_kit.pipeline.usage_ledger import LEDGER_NAME
from tests.dispatcher_support import FakeSpawner, install_spawner, processes_workspace
from tests.emergency_lane_support import build
from tests.lane_run_slots import as_owed_comment
from tests.tick_pass import Builder, install_builder, isolate, stored, tick, warm_unit_graphs

pytestmark = pytest.mark.usefixtures("scripted_engine")


@pytest.fixture(autouse=True)
def warmed(tmp_path: Path) -> None:
    warm_unit_graphs(tmp_path)


@pytest.fixture(autouse=True)
def isolated(monkeypatch: pytest.MonkeyPatch) -> None:
    isolate(monkeypatch)


@pytest.fixture
def builder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Builder:
    return install_builder(tmp_path, monkeypatch)


@pytest.fixture
def spawner(monkeypatch: pytest.MonkeyPatch) -> FakeSpawner:
    return install_spawner(monkeypatch)


def test_a_tick_admits_up_to_the_limit_marks_and_spawns_and_does_not_build(
    tmp_path: Path, builder: Builder, spawner: FakeSpawner
) -> None:
    inst = processes_workspace(tmp_path, max_concurrent=2)
    builder.store.upsert([stored("a/1"), stored("b/1"), stored("c/1")])

    assert tick(inst) == 0

    assert sorted(spawner.units) == ["a/1", "b/1"]
    assert {kind for kind, _unit in spawner.calls} == {"build"}
    marked = [unit.id for unit in builder.store.all() if unit.starting is not None]
    assert sorted(marked) == ["a/1", "b/1"]
    assert builder.started == [], "the dispatcher builds nothing itself"


def test_a_tick_writes_one_sample_row_and_the_slot_gauges_for_the_slots_it_left(
    tmp_path: Path, builder: Builder, spawner: FakeSpawner, monkeypatch: pytest.MonkeyPatch
) -> None:
    inst = processes_workspace(tmp_path, max_concurrent=1)
    builder.store.upsert([stored("a/1"), stored("b/1")])
    gauges: dict[str, int] = {}
    monkeypatch.setattr(
        cli.telemetry, "level", lambda name, value, **attributes: gauges.update({name: value})
    )

    assert tick(inst) == 0

    lines = [json.loads(line) for line in (inst.state_dir / LEDGER_NAME).read_text().splitlines()]
    (sample,) = [line for line in lines if line.get("kind") == "sample"]
    assert (sample["running"], sample["queued"], sample["free_workers"]) == (1, 1, 0)
    assert (sample["limit"], sample["cap"]) == (50, 1)
    assert gauges["abk.slots.free"] == sample["free_workers"] == 0
    assert gauges["abk.slots.idle_with_ready"] == 0


def never_built(*args: object, **kwargs: object) -> None:
    raise AssertionError("the tick built a resolution lane")


def in_review_run_in_a_worker(inst: Installation, builder: Builder) -> None:
    """`c1/1` is in review and a resolve worker (this process) restacks it."""
    unit, _state = build("c1/1", IN_REVIEW)
    builder.store.upsert([unit])
    builder.store.set_state("c1/1", IN_REVIEW, branch="spec/c1/1", pr=9)
    stored_unit = builder.store.get("c1/1")
    write_worker_record(inst.state_dir, project_key(stored_unit), stored_unit, base="main")


def test_a_tick_builds_no_resolution_lane_and_ends_without_waiting_for_a_run(
    tmp_path: Path, builder: Builder, spawner: FakeSpawner, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in ("build_restack_lane", "ResolutionLane", "ResolutionLanes"):
        monkeypatch.setattr(cli, name, never_built, raising=False)
    inst = processes_workspace(tmp_path)
    in_review_run_in_a_worker(inst, builder)

    assert tick(inst) == 0

    assert lane_held_by_record(inst.state_dir) == {"c1/1"}, "the worker's run is left going"


def test_the_slot_sample_counts_a_run_in_a_resolve_worker_as_running(
    tmp_path: Path, builder: Builder, spawner: FakeSpawner
) -> None:
    inst = processes_workspace(tmp_path, max_concurrent=1)
    in_review_run_in_a_worker(inst, builder)

    assert tick(inst) == 0

    lines = [json.loads(line) for line in (inst.state_dir / LEDGER_NAME).read_text().splitlines()]
    (sample,) = [line for line in lines if line.get("kind") == "sample"]
    assert sample["running"] == 1


def level_gauges(monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
    """The telemetry levels a tick sets, by name."""
    gauges: dict[str, int] = {}
    monkeypatch.setattr(
        cli.telemetry, "level", lambda name, value, **attributes: gauges.update({name: value})
    )
    return gauges


def test_a_run_owed_beyond_the_cap_beside_a_run_in_a_resolve_worker_is_the_waiting_gauge(
    tmp_path: Path, builder: Builder, spawner: FakeSpawner, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The one build slot is held by a build, so the run owed beyond the cap cannot overflow.
    inst = processes_workspace(tmp_path, max_concurrent=1, resolutions=1)
    busy, _state = build("c1/3", RUNNING)
    builder.store.upsert([busy])
    builder.store.set_state("c1/3", RUNNING, branch="spec/c1/3")
    builder.store.set_starting(
        "c1/3", Starting(worker="build-1", until=datetime.now(UTC) + timedelta(hours=1))
    )
    in_review_run_in_a_worker(inst, builder)
    owed, _state = build("c1/2", IN_REVIEW)
    builder.store.upsert([owed])
    as_owed_comment(builder.store, "c1/2")
    gauges = level_gauges(monkeypatch)

    assert tick(inst) == 0

    assert gauges["abk.restacks.running"] == 1
    assert gauges["abk.restacks.waiting"] == 1


def test_a_run_whose_resolve_worker_the_tick_just_started_is_running_and_not_waiting(
    tmp_path: Path, builder: Builder, spawner: FakeSpawner, monkeypatch: pytest.MonkeyPatch
) -> None:
    inst = processes_workspace(tmp_path, resolutions=1)
    owed, _state = build("c1/1", IN_REVIEW)
    builder.store.upsert([owed])
    as_owed_comment(builder.store, "c1/1")
    gauges = level_gauges(monkeypatch)

    assert tick(inst) == 0

    assert [kind for kind, _unit in spawner.calls] == ["resolve"], "a worker is claimed, no record"
    assert gauges["abk.restacks.running"] == 1
    assert gauges["abk.restacks.waiting"] == 0


def test_an_idle_tick_starts_nothing_and_makes_no_host_call(
    tmp_path: Path, builder: Builder, spawner: FakeSpawner, monkeypatch: pytest.MonkeyPatch
) -> None:
    inst = processes_workspace(tmp_path)
    builder.store.upsert([stored("a/1")])
    assert tick(inst) == 0
    assert spawner.units == ["a/1"]
    builder.store.set_starting("a/1", None)
    builder.store.set_state("a/1", HELD, note="needs a person", cause=Cause.NEEDS_HUMAN)

    def host(*args: object, **kwargs: object) -> None:
        raise AssertionError("an idle dispatcher calls the host")

    for name in ("poll_all", "fetch_all", "current_usage"):
        monkeypatch.setattr(cli, name, host)

    assert tick(inst) == 0
    assert spawner.units == ["a/1"]


def test_a_second_dispatcher_exits_at_once_and_says_why(
    tmp_path: Path, builder: Builder, spawner: FakeSpawner, capsys: pytest.CaptureFixture[str]
) -> None:
    inst = processes_workspace(tmp_path)
    builder.store.upsert([stored("a/1")])

    with file_lock(inst.locks_dir / "dispatcher.lock"):
        code = tick(inst)

    assert code == 0
    assert spawner.calls == []
    assert builder.store.get("a/1").starting is None
    assert "dispatcher" in capsys.readouterr().out


def test_a_unit_whose_usage_pause_has_not_reached_its_time_holds_its_place_and_gets_no_worker(
    tmp_path: Path, builder: Builder, spawner: FakeSpawner, monkeypatch: pytest.MonkeyPatch
) -> None:
    inst = processes_workspace(tmp_path, in_progress=1)
    builder.store.upsert([stored("a/1"), stored("b/1")])
    builder.store.set_state("a/1", RUNNING, branch="spec/a/1")
    builder.store.set_usage_pause("a/1", datetime.now(UTC) + timedelta(hours=1))
    monkeypatch.setattr(
        cli, "may_start_unit", lambda reading, **_: Decision(may_start=False, reason="paused")
    )

    assert tick(inst) == 0
    assert spawner.calls == [], "a/1 waits for its time, and b/1 has no place to take"
    assert builder.store.get("b/1").starting is None

    builder.store.set_usage_pause("a/1", datetime.now(UTC) - timedelta(minutes=1))
    monkeypatch.setattr(
        cli, "may_start_unit", lambda reading, **_: Decision(may_start=True, reason="plenty")
    )

    assert tick(inst) == 0
    assert spawner.units == ["a/1"], "at its time the unit is given its worker"


def test_a_unit_whose_usage_pause_a_fresh_reading_lifts_is_spawned_before_its_time(
    tmp_path: Path, builder: Builder, spawner: FakeSpawner
) -> None:
    # `isolate` makes the usage decision allow a start, so the pause need not run to its time.
    inst = processes_workspace(tmp_path, in_progress=1)
    builder.store.upsert([stored("a/1")])
    builder.store.set_state("a/1", RUNNING, branch="spec/a/1")
    builder.store.set_usage_pause("a/1", datetime.now(UTC) + timedelta(hours=1))

    assert tick(inst) == 0

    assert spawner.units == ["a/1"]
