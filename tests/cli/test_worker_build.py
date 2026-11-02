"""`abk worker build <unit>`: a unit's build as its own process (spec: unit-workers).

The worker takes the unit's branch lock, runs it to its next wait, records the outcome, releases
the lock and touches the wake file. The build is `tests/tick_pass.py`'s controlled builder."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from agent_build_kit.cli import build_parser
from agent_build_kit.cli.worker import cmd_worker_build
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.snapshots import WAKE
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import IN_REVIEW, PLANNED, RUNNING
from agent_build_kit.pipeline.workspaces import branch_held, branch_lock, lock_holder_gone
from tests.branch_lock_fakes import dead_pid, lock_held_by
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
def builder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Builder:
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
        worker(inst)

    assert builder.started == []
    assert store.get(UNIT).state == PLANNED


def test_a_worker_resumes_a_unit_whose_earlier_worker_was_killed(
    inst: Installation, builder: Builder
) -> None:
    store = seed(builder)
    store.set_state(UNIT, RUNNING, branch=BRANCH)
    lock_held_by(inst, BRANCH, dead_pid())
    assert lock_holder_gone(BRANCH, root=inst.locks_dir) is True

    code = worker(inst)

    assert code == 0
    assert builder.started == [UNIT]
    assert store.get(UNIT).state == IN_REVIEW
    assert not branch_held(BRANCH, root=inst.locks_dir)


def test_the_command_is_abk_worker_build() -> None:
    args = build_parser().parse_args(["worker", "build", UNIT])

    assert args.unit == UNIT
    assert args.func is cmd_worker_build


def test_the_workers_module_is_on_the_drift_list() -> None:
    assert "agent_build_kit.cli.worker" in WORKER_ENTRY_POINTS
