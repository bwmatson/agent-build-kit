"""The spawner: a worker as a transient systemd user unit when the user manager answers, else a
detached process in its own session whose output goes to the run log."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from agent_build_kit.pipeline.spawn import spawn, user_manager_available
from tests.conftest import make_installation
from tests.loginctl_fake import Loginctl

UNIT = "feature/1"


class Popen:
    """Records the call a detached start makes, and stands in for the process it returns."""

    pid = 4242

    def __init__(self, argv: list[str], **kwargs: Any) -> None:
        self.argv = argv
        self.kwargs = kwargs


def started_by_systemd(tmp_path: Path, **workers: object) -> list[str]:
    inst = make_installation(tmp_path / "planning", workers=workers)
    run = Loginctl("yes")
    worker = spawn(inst, "build", UNIT, user_manager=True, run=run, popen=Popen)
    assert worker.how == "systemd"
    [argv] = [call for call in run.calls if call[0] == "systemd-run"]
    return argv


def test_with_the_user_manager_the_worker_is_a_transient_unit_with_the_configured_limits(
    tmp_path: Path,
) -> None:
    argv = started_by_systemd(tmp_path, memory_max="2G", cpu_weight=200)

    assert argv[:3] == ["systemd-run", "--user", "--collect"]
    assert argv[argv.index("--unit") + 1].startswith("abk-")
    assert "-worker-" in argv[argv.index("--unit") + 1]
    assert {"MemoryMax=2G", "CPUWeight=200"} <= set(argv)
    assert argv[-3:] == ["worker", "build", UNIT]


def test_the_transient_unit_keeps_the_callers_path_and_the_installation_directory(
    tmp_path: Path,
) -> None:
    inst = make_installation(tmp_path / "planning")
    run = Loginctl("yes")

    spawn(inst, "build", UNIT, user_manager=True, run=run, popen=Popen)

    [argv] = [call for call in run.calls if call[0] == "systemd-run"]
    command = argv.index(sys.executable)
    assert argv.index("--setenv=PATH") < command
    assert argv.index(f"--working-directory={inst.root}") < command


def test_the_transient_unit_is_given_the_toolchain_variable_the_dispatcher_has(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VOLTA_HOME", str(tmp_path / "volta"))
    inst = make_installation(tmp_path / "planning")
    run = Loginctl("yes")

    spawn(inst, "build", UNIT, user_manager=True, run=run, popen=Popen)

    [argv] = [call for call in run.calls if call[0] == "systemd-run"]
    assert "--setenv=VOLTA_HOME" in argv
    assert argv.index("--setenv=VOLTA_HOME") < argv.index(sys.executable)


def test_a_dispatcher_without_the_toolchain_variable_passes_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("VOLTA_HOME", raising=False)
    inst = make_installation(tmp_path / "planning")
    run = Loginctl("yes")

    spawn(inst, "build", UNIT, user_manager=True, run=run, popen=Popen)

    [argv] = [call for call in run.calls if call[0] == "systemd-run"]
    assert not [word for word in argv if "VOLTA_HOME" in word]
    assert "--setenv=PATH" in argv


def test_a_limit_that_is_not_set_adds_no_property(tmp_path: Path) -> None:
    argv = started_by_systemd(tmp_path)

    assert not [arg for arg in argv if arg.startswith(("MemoryMax=", "CPUWeight="))]
    assert "-p" not in argv


def test_only_the_limit_that_is_set_adds_its_property(tmp_path: Path) -> None:
    argv = started_by_systemd(tmp_path, memory_max="1G")

    assert "MemoryMax=1G" in argv
    assert not [arg for arg in argv if arg.startswith("CPUWeight=")]


def test_without_the_user_manager_the_worker_is_a_detached_process_logging_to_the_run_log(
    tmp_path: Path,
) -> None:
    inst = make_installation(tmp_path / "planning", workers={"memory_max": "2G"})
    started: list[Popen] = []

    def popen(argv: list[str], **kwargs: Any) -> Popen:
        started.append(Popen(argv, **kwargs))
        return started[-1]

    run = Loginctl("yes")
    worker = spawn(inst, "build", UNIT, user_manager=False, run=run, popen=popen)

    [process] = started
    assert (worker.how, worker.id) == ("process", "4242")
    assert not run.calls, "no systemd-run without the user manager"
    assert process.argv[-3:] == ["worker", "build", UNIT]
    assert process.kwargs["start_new_session"] is True
    assert "env" not in process.kwargs, "a detached worker keeps the dispatcher's environment"
    assert process.kwargs["stdin"] == subprocess.DEVNULL
    assert process.kwargs["stderr"] == subprocess.STDOUT
    assert inst.state_dir in Path(process.kwargs["stdout"].name).parents


def test_the_user_manager_is_available_when_systemctl_answers(tmp_path: Path) -> None:
    def running(argv, **kwargs):
        return subprocess.CompletedProcess(argv, 0, "running\n", "")

    def no_bus(argv, **kwargs):
        return subprocess.CompletedProcess(argv, 1, "", "Failed to connect to bus")

    def missing(argv, **kwargs):
        raise FileNotFoundError("systemctl")

    assert user_manager_available(running) is True
    assert user_manager_available(no_bus) is False
    assert user_manager_available(missing) is False
