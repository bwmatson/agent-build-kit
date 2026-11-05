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
    inst: Installation, unit_of_branch: Mapping[str, tuple[str, str]], run: Run | None = None
) -> list[str]:
    """One line per running worker (kind, unit, pid, start time in UTC, usage), or one saying
    none run. `unit_of_branch` maps a unit's branch to its id and its repo's name; a holder is a
    worker only when its unit's repo runs workers, since a build of any other repo is a thread
    of the tick. A holder on a branch no unit names is shown under the branch, without usage,
    when any repo runs workers."""
    if not inst.has_worker_repo():
        return ["workers: none (builds run in the tick)"]
    run = run or subprocess.run
    lines = []
    for holder in live_holders(inst.locks_dir):
        branch = holder.get("branch")
        if not isinstance(branch, str):
            continue
        known = unit_of_branch.get(branch)
        if known and inst.workers_mode(known[1]) != "processes":
            continue
        unit = known[0] if known else None
        usage = _usage(inst, unit, run) if unit else ""
        lines.append(f"worker build {unit or branch}: pid {holder['pid']}{_since(holder)}{usage}")
    return lines or ["workers: none running"]
