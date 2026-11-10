"""Starting a worker as its own process: a transient systemd user unit, or a detached process."""

from __future__ import annotations

import os
import re
import subprocess
import sys
import uuid
from collections.abc import Callable
from typing import Any, Literal

from agent_build_kit import timers
from agent_build_kit.installation import Installation
from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.run_log import run_log_dir

Run = Callable[..., subprocess.CompletedProcess]

# What `systemctl --user is-system-running` prints when the manager can start a unit.
_USABLE = ("running", "degraded")
# Variables a worker takes from its dispatcher beside `PATH`: where a toolchain manager keeps its
# tools, which a worker's shims read.
_TOOLCHAIN_VARIABLES = ("VOLTA_HOME",)


class Worker(Frozen):
    """A started worker: the systemd unit name (`how == "systemd"`) or the pid (`"process"`)."""

    id: str
    how: Literal["systemd", "process"]


def user_manager_available(run: Run | None = None) -> bool:
    """Whether the systemd user manager answers `systemctl --user is-system-running`."""
    run = run or subprocess.run
    try:
        done = run(
            ["systemctl", "--user", "is-system-running"],
            check=False,
            capture_output=True,
            text=True,
            timeout=timers.LOGINCTL_TIMEOUT,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return done.stdout.strip() in _USABLE


def _safe(unit: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.]+", "-", unit).strip("-")


def worker_unit_prefix(inst: Installation, unit: str) -> str:
    """The transient unit name of `unit`'s worker without its `-<6 hex>` suffix: the one place
    the name is spelled, for the spawner and for whoever looks a worker's unit up."""
    return f"abk-{timers.slug(inst.root)}-worker-{_safe(unit)}"


def spawn(
    inst: Installation,
    kind: str,
    unit: str,
    *,
    user_manager: bool,
    run: Run | None = None,
    popen: Callable[..., Any] | None = None,
) -> Worker:
    """Start `abk worker <kind> <unit>`: through `run` as `systemd-run --user --collect` when
    `user_manager`, else through `popen` as a detached process in its own session."""
    command = [
        sys.executable,
        "-m",
        "agent_build_kit",
        "--config",
        str(inst.root / "abk.yaml"),
        "worker",
        kind,
        unit,
    ]
    safe = _safe(unit)
    if user_manager:
        name = f"{worker_unit_prefix(inst, unit)}-{uuid.uuid4().hex[:6]}"
        limits = inst.config.workers
        properties = [
            *(["-p", f"MemoryMax={limits.memory_max}"] if limits.memory_max else []),
            *(["-p", f"CPUWeight={limits.cpu_weight}"] if limits.cpu_weight else []),
        ]
        # A transient unit starts with the manager's bare environment and directory. `--setenv`
        # with a name alone takes the value from systemd-run's own environment, which for a
        # dispatcher is the tick unit's PATH, so the worker finds the tools the detached
        # fallback finds. The toolchain manager's variable goes the same way when the
        # dispatcher has it: without it a worker's `node` shim looks for a toolchain in a home
        # folder that has none, and goes to the network for one.
        argv = [
            "systemd-run",
            "--user",
            "--collect",
            "--unit",
            name,
            "--setenv=PATH",
            *(f"--setenv={name}" for name in _TOOLCHAIN_VARIABLES if name in os.environ),
            f"--working-directory={inst.root}",
            *properties,
            *command,
        ]
        (run or subprocess.run)(argv, check=True, capture_output=True, text=True)
        return Worker(id=name, how="systemd")
    directory = run_log_dir(inst.state_dir)
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / f"worker-{kind}-{safe}-{uuid.uuid4().hex[:6]}.log").open("ab") as log:
        process = (popen or subprocess.Popen)(
            command,
            start_new_session=True,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
    return Worker(id=str(process.pid), how="process")
