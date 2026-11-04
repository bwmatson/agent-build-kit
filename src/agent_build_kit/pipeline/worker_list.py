"""The workers `abk status` lists: the live holders of unit branch locks, with the cgroup CPU and
memory systemd reports for a worker that runs as a transient unit."""

from __future__ import annotations

import subprocess
from collections.abc import Mapping
from datetime import datetime

from agent_build_kit import timers
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.spawn import Run, worker_unit_prefix
from agent_build_kit.pipeline.workspaces import live_holders

_MIB = 1024 * 1024
# What systemd before v244 reports for a counter when accounting is off.
_NO_READING = 2**64 - 1


def _reading(values: Mapping[str, str], key: str) -> int | None:
    found = values.get(key, "")
    return int(found) if found.isdecimal() and int(found) != _NO_READING else None


def _usage(inst: Installation, unit: str, run: Run) -> str:
    """` — cpu 90s, memory 256 MiB` from `systemctl --user show` for the unit's transient unit
    (the spawner's name and a six-character suffix, so no other unit's worker matches), or
    nothing when systemd does not report it."""
    try:
        done = run(
            [
                "systemctl",
                "--user",
                "show",
                "--property=MemoryCurrent,CPUUsageNSec",
                f"{worker_unit_prefix(inst, unit)}-??????.service",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=timers.LOGINCTL_TIMEOUT,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    if done.returncode:
        return ""
    values = dict(line.split("=", 1) for line in done.stdout.splitlines() if "=" in line)
    parts = []
    if (cpu := _reading(values, "CPUUsageNSec")) is not None:
        parts.append(f"cpu {cpu / 1e9:.0f}s")
    if (memory := _reading(values, "MemoryCurrent")) is not None:
        parts.append(f"memory {memory // _MIB} MiB")
    return f" — {', '.join(parts)}" if parts else ""


def _since(holder: dict) -> str:
    try:
        return f", since {datetime.fromisoformat(holder['at']):%Y-%m-%d %H:%M} UTC"
    except (KeyError, TypeError, ValueError):
        return ""


def worker_status_lines(
    inst: Installation, unit_of_branch: Mapping[str, str], run: Run | None = None
) -> list[str]:
    """One line per running worker (kind, unit, pid, start time in UTC, usage), or one saying
    none run. `unit_of_branch` maps a unit's branch to its id; a holder on a branch no unit
    names is shown under the branch, without usage. In `threads` mode the tick builds in its
    own threads, so no process is a worker and none is listed."""
    if inst.config.workers.mode != "processes":
        return ["workers: none (builds run in the tick)"]
    holders = [h for h in live_holders(inst.locks_dir) if isinstance(h.get("branch"), str)]
    if not holders:
        return ["workers: none running"]
    run = run or subprocess.run
    lines = []
    for holder in holders:
        unit = unit_of_branch.get(holder["branch"])
        usage = _usage(inst, unit, run) if unit else ""
        lines.append(
            f"worker build {unit or holder['branch']}: pid {holder['pid']}{_since(holder)}{usage}"
        )
    return lines
