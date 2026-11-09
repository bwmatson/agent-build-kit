"""`abk status` lists each running worker, or says none run (spec: unit-workers)."""

from __future__ import annotations

import json
import os
import re
import subprocess
from datetime import UTC, datetime
from fnmatch import fnmatch
from pathlib import Path

import pytest

from agent_build_kit.cli.pipeline import store_for
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.spawn import spawn
from agent_build_kit.pipeline.unit_store import Pull
from agent_build_kit.pipeline.units import UnitState
from agent_build_kit.pipeline.workspaces import branch_lock
from tests.conftest import make_installation, run_status
from tests.tick_pass import stored

UNIT = "feature/1"
OTHER = "feature-1/2"
BRANCH = "spec/feature/1"
MIB = 1024 * 1024
UNREPORTED = 2**64 - 1

real_run = subprocess.run


def installation(tmp_path: Path, **overrides) -> Installation:
    return make_installation(tmp_path / "planning", **overrides)


@pytest.fixture
def inst(tmp_path: Path) -> Installation:
    return installation(tmp_path)


def worker_lines(lines: list[str]) -> list[str]:
    return [line for line in lines if "worker build" in line]


def none_running(lines: list[str]) -> list[str]:
    return [line for line in lines if re.search(r"workers?: none", line, re.I)]


def seed(inst: Installation, unit: str = UNIT, **state) -> None:
    store = store_for(inst)
    store.upsert([stored(unit)])
    if state:
        store.set_state(unit, **state)


def worker_names(inst: Installation, *units: str) -> list[str]:
    """The names `spawn` gives the transient units of these units' workers: what it passes to
    `systemd-run --unit`."""
    names: list[str] = []

    def run(argv, *args, **kwargs):
        names.append(argv[argv.index("--unit") + 1])
        return subprocess.CompletedProcess(argv, 0, "", "")

    for unit in units:
        spawn(inst, "build", unit, user_manager=True, run=run)
    return names


class Systemd:
    """`systemctl --user show` answering the raw `Property=value` text, one block per started
    worker unit whose name matches the pattern it is asked, `memory[name]` bytes of memory each;
    every other command is the real one."""

    def __init__(self, memory: dict[str, int] | None = None) -> None:
        self.memory = memory or {}
        self.asked: list[str] = []

    def __call__(self, argv, *args, **kwargs):
        if list(argv[:3]) != ["systemctl", "--user", "show"]:
            return real_run(argv, *args, **kwargs)
        pattern = argv[-1]
        self.asked.append(pattern)
        blocks = [
            f"MemoryCurrent={bytes_}\nCPUUsageNSec={90 * 10**9}\n"
            for name, bytes_ in self.memory.items()
            if fnmatch(f"{name}.service", pattern)
        ]
        if not blocks:
            return subprocess.CompletedProcess(argv, 1, "", "Unit could not be found.")
        return subprocess.CompletedProcess(argv, 0, "\n".join(blocks), "")


def with_systemd(monkeypatch: pytest.MonkeyPatch, systemd: Systemd | None = None) -> Systemd:
    systemd = systemd or Systemd()
    monkeypatch.setattr(subprocess, "run", systemd)
    return systemd


def test_no_worker_running_says_so(
    inst: Installation, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lines = run_status(inst, monkeypatch, capsys)

    assert none_running(lines)
    assert not worker_lines(lines)


def test_a_worker_holding_a_branch_lock_is_listed_with_kind_unit_pid_and_start(
    inst: Installation, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    with_systemd(monkeypatch)
    seed(inst)
    with branch_lock(BRANCH, root=inst.locks_dir):
        [lock] = inst.locks_dir.glob("spec_*.lock")
        record = json.loads(lock.read_text())

        lines = run_status(inst, monkeypatch, capsys)

    [line] = worker_lines(lines)
    assert f"build {UNIT}:" in line
    assert f"pid {os.getpid()}" in line
    # The start time is the one the lock recorded, in UTC.
    assert record["at"][11:16] in line
    assert not none_running(lines)


def test_cgroup_cpu_and_memory_are_shown_when_systemd_reports_them(
    inst: Installation, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    [name] = worker_names(inst, UNIT)
    systemd = with_systemd(monkeypatch, Systemd({name: 256 * MIB}))
    seed(inst)
    with branch_lock(BRANCH, root=inst.locks_dir):
        lines = run_status(inst, monkeypatch, capsys)

    [line] = worker_lines(lines)
    assert systemd.asked
    assert re.search(r"256\s?(MiB|M)\b", line)
    assert re.search(r"cpu", line, re.I)


def test_another_units_worker_is_not_taken_for_this_ones(
    inst: Installation, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    name, other = worker_names(inst, UNIT, OTHER)
    with_systemd(monkeypatch, Systemd({name: 256 * MIB, other: 512 * MIB}))
    seed(inst)
    with branch_lock(BRANCH, root=inst.locks_dir):
        lines = run_status(inst, monkeypatch, capsys)

    [line] = worker_lines(lines)
    assert "256 MiB" in line
    assert "512" not in line


def test_the_query_names_the_unit_the_spawner_named(
    inst: Installation, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    [name] = worker_names(inst, UNIT)
    systemd = with_systemd(monkeypatch, Systemd({name: MIB}))
    seed(inst)
    with branch_lock(BRANCH, root=inst.locks_dir):
        run_status(inst, monkeypatch, capsys)

    assert [pattern for pattern in systemd.asked if fnmatch(f"{name}.service", pattern)]


def test_a_late_fix_build_is_listed_under_its_unit_and_reads_the_units_usage(
    inst: Installation, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    [name] = worker_names(inst, UNIT)
    with_systemd(monkeypatch, Systemd({name: 256 * MIB}))
    seed(inst)
    store = store_for(inst)
    merged = datetime(2026, 1, 1, tzinfo=UTC)
    store.set_state(UNIT, UnitState.MERGED, branch="spec/feature/1-fix1")
    store.set_pulls(
        UNIT,
        [
            Pull(number=1, branch=BRANCH, merged_at=merged),
            Pull(number=2, branch="spec/feature/1-fix1", role="fix"),
        ],
    )
    with branch_lock("spec/feature/1-fix1", root=inst.locks_dir):
        lines = run_status(inst, monkeypatch, capsys)

    [line] = worker_lines(lines)
    assert f"build {UNIT}:" in line
    assert "fix1" not in line
    assert "256 MiB" in line


def test_a_non_default_branch_prefix_is_not_taken_for_part_of_the_unit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    inst = installation(tmp_path, git={"branch_prefix": "abk/spec/"})
    [name] = worker_names(inst, UNIT)
    with_systemd(monkeypatch, Systemd({name: 256 * MIB}))
    seed(inst)
    with branch_lock("abk/spec/feature/1", root=inst.locks_dir):
        lines = run_status(inst, monkeypatch, capsys)

    [line] = worker_lines(lines)
    assert f"build {UNIT}:" in line
    assert "spec/feature" not in line
    assert "256 MiB" in line


def test_a_lock_on_a_branch_no_unit_has_is_listed_under_the_branch(
    inst: Installation, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    with_systemd(monkeypatch)
    with branch_lock("spec/gone/9", root=inst.locks_dir):
        lines = run_status(inst, monkeypatch, capsys)

    [line] = worker_lines(lines)
    assert "spec/gone/9" in line


def test_no_cpu_or_memory_is_shown_when_systemd_does_not_report_them(
    inst: Installation, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    with_systemd(monkeypatch)
    seed(inst)
    with branch_lock(BRANCH, root=inst.locks_dir):
        lines = run_status(inst, monkeypatch, capsys)

    [line] = worker_lines(lines)
    assert not re.search(r"cpu|mem", line, re.I)


def test_a_counter_systemd_reports_as_unavailable_is_not_shown(
    inst: Installation, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    [name] = worker_names(inst, UNIT)
    with_systemd(monkeypatch, Systemd({name: UNREPORTED}))
    seed(inst)
    with branch_lock(BRANCH, root=inst.locks_dir):
        lines = run_status(inst, monkeypatch, capsys)

    [line] = worker_lines(lines)
    assert "memory" not in line


def test_a_lock_whose_holder_is_gone_is_not_a_running_worker(
    inst: Installation, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    with_systemd(monkeypatch)
    finished = subprocess.Popen(["true"])
    finished.wait()
    inst.locks_dir.mkdir(parents=True, exist_ok=True)
    record = {"pid": finished.pid, "branch": BRANCH, "at": "2026-01-01T00:00:00+00:00"}
    (inst.locks_dir / "spec_feature_1.lock").write_text(json.dumps(record))

    lines = run_status(inst, monkeypatch, capsys)

    assert not worker_lines(lines)
    assert none_running(lines)
