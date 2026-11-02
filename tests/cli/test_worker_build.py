"""`abk worker build <unit>`: a unit's build as its own process (spec: unit-workers).

The worker takes the unit's branch lock, runs it to its next wait, records the outcome, releases
the lock and touches the wake file. The build is `tests/tick_pass.py`'s controlled builder."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from agent_build_kit import telemetry
from agent_build_kit.cli import build_parser
from agent_build_kit.cli import pipeline as cli
from agent_build_kit.cli import worker as worker_cli
from agent_build_kit.cli.worker import cmd_worker_build
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline import usage_guard
from agent_build_kit.pipeline.snapshots import WAKE
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import IN_REVIEW, PLANNED
from agent_build_kit.pipeline.workspaces import branch_held, branch_lock
from tests.drift.test_workers_do_not_poll import WORKER_ENTRY_POINTS
from tests.tick_pass import Builder, install_builder, isolate, stored, warm_unit_graphs, workspace

UNIT = "feature/1"
BRANCH = "spec/feature/1"


@pytest.fixture
def inst(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Installation:
    isolate(monkeypatch)
    warm_unit_graphs(tmp_path)
    return workspace(tmp_path)


@pytest.fixture
def builder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, scripted_engine: None) -> Builder:
    return install_builder(tmp_path, monkeypatch)


def worker(inst: Installation, unit: str = UNIT) -> int:
    return cmd_worker_build(argparse.Namespace(unit=unit), inst)


def seed(builder: Builder) -> UnitStore:
    builder.store.upsert([stored(UNIT)])
    return builder.store


def test_a_worker_builds_under_the_branch_lock_and_leaves_its_outcome(
    inst: Installation, builder: Builder
) -> None:
    store = seed(builder)
    held_while_building: list[bool] = []
    builder.before_running[UNIT] = lambda: held_while_building.append(
        branch_held(BRANCH, root=inst.locks_dir)
    )

    code = worker(inst)

    assert code == 0
    assert held_while_building == [True]
    assert store.get(UNIT).state == IN_REVIEW
    assert not branch_held(BRANCH, root=inst.locks_dir)
    assert list(inst.locks_dir.glob("*.lock")) == []
    assert (inst.state_dir / WAKE).exists()


def test_a_worker_whose_unit_another_process_holds_does_not_build(
    inst: Installation, builder: Builder
) -> None:
    store = seed(builder)

    with branch_lock(BRANCH, root=inst.locks_dir):
        code = worker(inst)

    assert code == 0
    assert builder.started == []
    assert store.get(UNIT).state == PLANNED
    assert (inst.state_dir / WAKE).exists()


def test_a_worker_for_a_unit_no_longer_in_the_store_skips_it_and_wakes(
    inst: Installation, builder: Builder
) -> None:
    code = worker(inst, "gone/1")

    assert code == 0
    assert builder.started == []
    assert (inst.state_dir / WAKE).exists()


def test_a_run_paused_with_no_time_decides_its_resume_from_the_snapshot(
    inst: Installation, builder: Builder, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = seed(builder)
    builder.scripts[UNIT] = lambda: "paused"

    def endpoint(*args: object, **kwargs: object) -> None:
        raise AssertionError("a worker read the usage endpoint")

    monkeypatch.setattr(cli, "current_usage", endpoint)
    monkeypatch.setattr(usage_guard, "read_live_usage", endpoint)

    code = worker(inst)

    assert code == 0
    assert store.get(UNIT).state == PLANNED
    assert (inst.state_dir / "paused.json").exists()


@pytest.mark.parametrize("crash", [False, True])
def test_telemetry_is_started_before_the_build_and_flushed_after_it(
    inst: Installation, builder: Builder, monkeypatch: pytest.MonkeyPatch, crash: bool
) -> None:
    seed(builder)
    calls: list[str] = []

    def build(*args: object, **kwargs: object) -> bool:
        calls.append("build")
        if crash:
            raise RuntimeError("crashed")
        return True

    monkeypatch.setattr(telemetry, "init", lambda: calls.append("init") or False)
    monkeypatch.setattr(telemetry, "shutdown", lambda: calls.append("shutdown"))
    monkeypatch.setattr(worker_cli, "build_unit", build)

    if crash:
        with pytest.raises(RuntimeError):
            worker(inst)
    else:
        assert worker(inst) == 0

    assert calls == ["init", "build", "shutdown"]
    assert (inst.state_dir / WAKE).exists()


def test_the_command_is_abk_worker_build() -> None:
    args = build_parser().parse_args(["worker", "build", UNIT])

    assert args.unit == UNIT
    assert args.func is cmd_worker_build


def test_the_workers_module_is_on_the_drift_list() -> None:
    assert "agent_build_kit.cli.worker" in WORKER_ENTRY_POINTS
