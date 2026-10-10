"""Units failed with the cause `environment`: they hold their place, the status
and the queue name them, a tick runs for them, and the pass resumes them once the
environment is healthy (spec: pipeline-environment).
"""

from __future__ import annotations

import argparse
import threading
import time
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.unit_store import Cause, UnitStore
from agent_build_kit.pipeline.units import FAILED, in_progress
from tests.cli.test_tick_scheduling import (  # noqa: F401
    Builder,
    builder,
    isolated,
    stored,
    tick,
    warm_unit_graphs,
)
from tests.conftest import make_installation
from tests.environment_fakes import FakeEnvironment, environment_cause

pytestmark = pytest.mark.usefixtures("scripted_engine")

NOTE = "environment unhealthy before tier 1"


def managed(
    tmp_path: Path, *, max_concurrent: int = 4, in_progress_limit: int = 50
) -> tuple[Installation, FakeEnvironment]:
    env = FakeEnvironment(tmp_path / "control")
    (tmp_path / "manifest.toml").write_text("version 1\n")
    inst = make_installation(
        tmp_path,
        planning={"state_dir": ".", "worktree_root": str(tmp_path.parent / "trees")},
        limits={
            "max_concurrent_stacks": max_concurrent,
            "max_units_in_progress": in_progress_limit,
        },
        environment=env.config(),
    )
    return inst, env


def waiting_for_environment(store: UnitStore, *unit_ids: str) -> None:
    store.upsert([stored(unit_id) for unit_id in unit_ids])
    for unit_id in unit_ids:
        store.set_state(unit_id, FAILED, note=NOTE, cause=environment_cause())


def status_lines(inst: Installation, capsys: pytest.CaptureFixture[str]) -> list[str]:
    capsys.readouterr()
    assert cli.cmd_status(argparse.Namespace(), inst) == 0
    return capsys.readouterr().out.splitlines()


# --- 3.3 the unit keeps its slot, and the status says what it waits for ---------------


def test_a_unit_waiting_for_the_environment_counts_in_progress_and_the_status_names_it(
    tmp_path: Path,
    builder: Builder,  # noqa: F811
    capsys: pytest.CaptureFixture[str],
) -> None:
    inst, _ = managed(tmp_path)
    waiting_for_environment(builder.store, "feature/1")
    store_unit = builder.store.get("feature/1")

    lines = status_lines(inst, capsys)

    assert in_progress(store_unit)
    line = next(line for line in lines if "feature/1" in line)
    assert "waiting for the environment" in line


def test_the_queue_line_names_units_waiting_for_the_environment(
    tmp_path: Path,
    builder: Builder,  # noqa: F811
    capsys: pytest.CaptureFixture[str],
) -> None:
    inst, _ = managed(tmp_path, in_progress_limit=1)
    waiting_for_environment(builder.store, "feature/1")

    lines = status_lines(inst, capsys)

    full = next(line for line in lines if line.startswith("queue is full"))
    assert "1 waiting for the environment" in full


def test_a_unit_failed_for_another_cause_is_not_named_as_waiting_for_the_environment(
    tmp_path: Path,
    builder: Builder,  # noqa: F811
    capsys: pytest.CaptureFixture[str],
) -> None:
    inst, _ = managed(tmp_path, in_progress_limit=1)
    builder.store.upsert([stored("feature/1")])
    builder.store.set_state("feature/1", FAILED, note="tier 1 failed", cause=Cause.FAILED)

    lines = status_lines(inst, capsys)

    assert not any("waiting for the environment" in line for line in lines)


# --- 3.4 the pass resumes them -------------------------------------------------------


def test_a_healthy_check_resumes_the_units_and_the_log_says_the_environment_was_restored(
    tmp_path: Path,
    builder: Builder,  # noqa: F811
    capsys: pytest.CaptureFixture[str],
) -> None:
    inst, env = managed(tmp_path)
    waiting_for_environment(builder.store, "feature/1", "feature/2")

    assert tick(inst) == 0

    assert sorted(builder.started) == ["feature/1", "feature/2"]
    assert "check" in env.calls()
    restored = [line for line in capsys.readouterr().out.splitlines() if "restored" in line]
    assert restored and "environment" in restored[0]


def test_units_still_waiting_are_not_resumed_while_the_environment_stays_broken(
    tmp_path: Path,
    builder: Builder,  # noqa: F811
) -> None:
    inst, env = managed(tmp_path)
    env.break_it()
    waiting_for_environment(builder.store, "feature/1")

    assert tick(inst) != 0

    assert builder.started == []
    stored_unit = builder.store.get("feature/1")
    assert (stored_unit.state, stored_unit.cause) == (FAILED, environment_cause())


def test_the_resumed_units_run_within_the_concurrency_limit(
    tmp_path: Path,
    builder: Builder,  # noqa: F811
) -> None:
    inst, _ = managed(tmp_path, max_concurrent=1)
    waiting_for_environment(builder.store, "feature/1", "feature/2", "feature/3")
    lock = threading.Lock()
    active = [0]
    peak = [0]

    def build() -> None:
        with lock:
            active[0] += 1
            peak[0] = max(peak[0], active[0])
        time.sleep(0.2)
        with lock:
            active[0] -= 1

    for unit_id in ("feature/1", "feature/2", "feature/3"):
        builder.scripts[unit_id] = build

    assert tick(inst) == 0

    assert sorted(builder.started) == ["feature/1", "feature/2", "feature/3"]
    assert peak[0] == 1


# --- 3.5 the check for work ----------------------------------------------------------


def test_only_a_unit_waiting_for_the_environment_makes_a_store_with_nothing_else_work(
    tmp_path: Path,
    builder: Builder,  # noqa: F811
) -> None:
    inst, _ = managed(tmp_path)
    builder.store.upsert([stored("feature/1")])
    builder.store.set_state("feature/1", FAILED, note="tier 1 failed", cause=Cause.FAILED)
    assert not cli.has_work(inst, builder.store), (
        "a unit failed for another cause waits for a person"
    )

    builder.store.set_state("feature/1", FAILED, note=NOTE, cause=environment_cause())

    assert cli.has_work(inst, builder.store)
