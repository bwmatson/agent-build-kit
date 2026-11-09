"""`abk tick` is a dispatcher (spec: unit-workers): it admits ready
units up to the limits, marks them `starting`, starts one worker for each and exits without waiting
for any; a second dispatcher exits at once; a unit with a usage pause that has not reached its time
is given no worker and still holds its place."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline.file_lock import file_lock
from agent_build_kit.pipeline.unit_store import Cause
from agent_build_kit.pipeline.units import HELD, RUNNING
from agent_build_kit.pipeline.usage_guard import Decision
from tests.dispatcher_support import FakeSpawner, install_spawner, processes_workspace
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
