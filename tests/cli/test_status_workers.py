"""`abk status` lists each running worker, or says none run (spec: unit-workers)."""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

import pytest

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.workspaces import branch_lock
from tests.conftest import make_installation, run_status

UNIT = "feature/1"
BRANCH = "spec/feature/1"
MEMORY_BYTES = 256 * 1024 * 1024
CPU_NSEC = 90 * 1_000_000_000

real_run = subprocess.run


@pytest.fixture
def inst(tmp_path: Path) -> Installation:
    return make_installation(tmp_path / "planning")


def worker_lines(lines: list[str]) -> list[str]:
    return [line for line in lines if UNIT in line and "worker" in line.lower()]


def none_running(lines: list[str]) -> list[str]:
    return [line for line in lines if re.search(r"workers?: none", line, re.I)]


def systemd_reports(monkeypatch: pytest.MonkeyPatch, *, answers: bool) -> list[list[str]]:
    """`systemctl --user show` answering the raw `Property=value` text, or failing; every other
    command is the real one."""
    asked: list[list[str]] = []

    def run(argv, *args, **kwargs):
        if list(argv[:3]) != ["systemctl", "--user", "show"]:
            return real_run(argv, *args, **kwargs)
        asked.append(list(argv))
        if not answers:
            return subprocess.CompletedProcess(argv, 1, "", "Unit could not be found.")
        text = f"MemoryCurrent={MEMORY_BYTES}\nCPUUsageNSec={CPU_NSEC}\n"
        return subprocess.CompletedProcess(argv, 0, text, "")

    monkeypatch.setattr(subprocess, "run", run)
    return asked


def test_no_worker_running_says_so(
    inst: Installation, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lines = run_status(inst, monkeypatch, capsys)

    assert none_running(lines)
    assert not worker_lines(lines)


def test_a_worker_holding_a_branch_lock_is_listed_with_kind_unit_pid_and_start(
    inst: Installation, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    systemd_reports(monkeypatch, answers=False)
    with branch_lock(BRANCH, root=inst.locks_dir):
        [lock] = inst.locks_dir.glob("spec_*.lock")
        record = json.loads(lock.read_text())

        lines = run_status(inst, monkeypatch, capsys)

    [line] = worker_lines(lines)
    assert "build" in line
    assert f"pid {os.getpid()}" in line
    # The start time is the one the lock recorded, in UTC.
    assert record["at"][11:16] in line
    assert not none_running(lines)


def test_cgroup_cpu_and_memory_are_shown_when_systemd_reports_them(
    inst: Installation, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    asked = systemd_reports(monkeypatch, answers=True)
    with branch_lock(BRANCH, root=inst.locks_dir):
        lines = run_status(inst, monkeypatch, capsys)

    [line] = worker_lines(lines)
    assert asked
    assert re.search(r"256\s?(MiB|M)\b", line)
    assert re.search(r"cpu", line, re.I)


def test_no_cpu_or_memory_is_shown_when_systemd_does_not_report_them(
    inst: Installation, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    systemd_reports(monkeypatch, answers=False)
    with branch_lock(BRANCH, root=inst.locks_dir):
        lines = run_status(inst, monkeypatch, capsys)

    [line] = worker_lines(lines)
    assert not re.search(r"cpu|mem", line, re.I)


def test_a_lock_whose_holder_is_gone_is_not_a_running_worker(
    inst: Installation, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    systemd_reports(monkeypatch, answers=False)
    finished = subprocess.Popen(["true"])
    finished.wait()
    inst.locks_dir.mkdir(parents=True, exist_ok=True)
    record = {"pid": finished.pid, "branch": BRANCH, "at": "2026-01-01T00:00:00+00:00"}
    (inst.locks_dir / "spec_feature_1.lock").write_text(json.dumps(record))

    lines = run_status(inst, monkeypatch, capsys)

    assert not worker_lines(lines)
    assert none_running(lines)
