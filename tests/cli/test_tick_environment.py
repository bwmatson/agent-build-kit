"""The tick keeps the environment current before it starts work, and `abk status`
says how it stands (spec: pipeline-environment).

`sync` and `check` are real child processes (`tests/environment_fakes.py`), driven
through `cmd_tick`; the builder stands in for the units' builds.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.installation import Installation
from tests.cli.test_tick_scheduling import (  # noqa: F401
    Builder,
    builder,
    isolated,
    stored,
    tick,
    warm_unit_graphs,
)
from tests.conftest import make_installation
from tests.environment_fakes import BROKEN_OUTPUT, FakeEnvironment

pytestmark = pytest.mark.usefixtures("scripted_engine")


def managed(tmp_path: Path) -> tuple[Installation, FakeEnvironment]:
    """A workspace whose environment is the fake one, over a manifest that exists."""
    env = FakeEnvironment(tmp_path / "control")
    (tmp_path / "manifest.toml").write_text("version 1\n")
    inst = make_installation(
        tmp_path,
        planning={"state_dir": ".", "worktree_root": str(tmp_path.parent / "trees")},
        limits={"max_concurrent_stacks": 4, "max_units_in_progress": 50},
        environment=env.config(),
    )
    return inst, env


def settled(tmp_path: Path, builder: Builder) -> tuple[Installation, FakeEnvironment]:  # noqa: F811
    """A workspace whose environment was synced and found healthy by an earlier tick."""
    inst, env = managed(tmp_path)
    builder.store.upsert([stored("earlier/1")])
    assert tick(inst) == 0
    env.clear()
    builder.started.clear()
    return inst, env


def status(inst: Installation, capsys: pytest.CaptureFixture[str]) -> list[str]:
    capsys.readouterr()
    assert cli.cmd_status(argparse.Namespace(), inst) == 0
    return capsys.readouterr().out.splitlines()


def environment_line(lines: list[str]) -> str:
    return next(line for line in lines if line.strip().lower().startswith("environment"))


# --- 2.1 a changed input -------------------------------------------------------------


def test_a_changed_input_runs_sync_records_the_hash_and_checks_before_any_unit_starts(
    tmp_path: Path,
    builder: Builder,  # noqa: F811
) -> None:
    inst, env = managed(tmp_path)
    builder.store.upsert([stored("feature/1")])
    seen: list[list[str]] = []
    builder.before_running["feature/1"] = lambda: seen.append(env.calls())

    assert tick(inst) == 0

    assert seen == [["sync", "check"]]
    env.clear()
    builder.store.upsert([stored("feature/2")])
    assert tick(inst) == 0
    assert env.calls() == ["check"], "the recorded hash means the next tick has nothing to sync"


def test_unchanged_inputs_and_a_passing_check_run_no_sync(
    tmp_path: Path,
    builder: Builder,  # noqa: F811
) -> None:
    inst, env = settled(tmp_path, builder)
    builder.store.upsert([stored("feature/1")])

    assert tick(inst) == 0

    assert builder.started == ["feature/1"]
    assert env.calls() == ["check"]


def test_an_input_changed_since_the_last_sync_runs_sync_again(
    tmp_path: Path,
    builder: Builder,  # noqa: F811
) -> None:
    inst, env = settled(tmp_path, builder)
    (tmp_path / "manifest.toml").write_text("version 2\n")
    builder.store.upsert([stored("feature/1")])

    assert tick(inst) == 0

    assert env.calls() == ["sync", "check"]


def test_an_idle_tick_runs_neither_sync_nor_check(
    tmp_path: Path,
    builder: Builder,  # noqa: F811
) -> None:
    inst, env = managed(tmp_path)

    assert tick(inst) == 0

    assert env.calls() == []


# --- 2.2 a failing check -------------------------------------------------------------


def test_a_failing_check_with_unchanged_inputs_syncs_once_and_the_pass_continues_on_a_pass(
    tmp_path: Path,
    builder: Builder,  # noqa: F811
) -> None:
    inst, env = settled(tmp_path, builder)
    env.break_it(sync_repairs=True)
    builder.store.upsert([stored("feature/1")])

    assert tick(inst) == 0

    assert env.calls() == ["check", "sync", "check"]
    assert builder.started == ["feature/1"]


def test_a_second_failure_starts_nothing_prints_the_output_and_exits_non_zero(
    tmp_path: Path,
    builder: Builder,  # noqa: F811
    capsys: pytest.CaptureFixture[str],
) -> None:
    inst, env = settled(tmp_path, builder)
    env.break_it()
    builder.store.upsert([stored("feature/1")])
    capsys.readouterr()

    assert tick(inst) != 0

    assert env.calls() == ["check", "sync", "check"], "one more sync, not a loop"
    assert builder.started == []
    assert BROKEN_OUTPUT in capsys.readouterr().out


# --- 2.3 the status ------------------------------------------------------------------


def test_status_prints_a_healthy_environment(
    tmp_path: Path,
    builder: Builder,  # noqa: F811
    capsys: pytest.CaptureFixture[str],
) -> None:
    inst, _ = settled(tmp_path, builder)

    line = environment_line(status(inst, capsys)).lower()

    assert "healthy" in line and "unhealthy" not in line


def test_status_prints_an_unhealthy_environment_with_the_output(
    tmp_path: Path,
    builder: Builder,  # noqa: F811
    capsys: pytest.CaptureFixture[str],
) -> None:
    inst, env = settled(tmp_path, builder)
    env.break_it()
    builder.store.upsert([stored("feature/1")])
    assert tick(inst) != 0

    lines = status(inst, capsys)

    assert "unhealthy" in environment_line(lines).lower()
    assert any(BROKEN_OUTPUT in line for line in lines)


def test_status_stops_calling_the_environment_unhealthy_once_a_tick_finds_it_mended(
    tmp_path: Path,
    builder: Builder,  # noqa: F811
    capsys: pytest.CaptureFixture[str],
) -> None:
    inst, env = settled(tmp_path, builder)
    env.break_it()
    builder.store.upsert([stored("feature/1")])
    assert tick(inst) != 0
    env.mend()

    assert tick(inst) == 0

    line = environment_line(status(inst, capsys)).lower()
    assert "healthy" in line and "unhealthy" not in line
