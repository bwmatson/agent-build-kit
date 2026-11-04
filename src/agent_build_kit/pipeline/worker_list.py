"""The workers `abk status` lists: the live holders of unit branch locks, with the cgroup CPU and
memory systemd reports for a worker that runs as a transient unit."""

from __future__ import annotations

import re
import subprocess
from datetime import datetime

from agent_build_kit import timers
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.workspaces import live_holders

_MIB = 1024 * 1024


def _usage(inst: Installation, unit: str) -> str:
    """` — cpu 90s, memory 256 MiB` from `systemctl --user show` for the unit's transient unit,
    or nothing when systemd does not report it."""
    safe = re.sub(r"[^A-Za-z0-9_.]+", "-", unit).strip("-")
    try:
        done = subprocess.run(
            [
                "systemctl",
                "--user",
                "show",
                "--property=MemoryCurrent,CPUUsageNSec",
                f"abk-{timers.slug(inst.root)}-worker-{safe}-*",
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
    if values.get("CPUUsageNSec", "").isdecimal():
        parts.append(f"cpu {int(values['CPUUsageNSec']) / 1e9:.0f}s")
    if values.get("MemoryCurrent", "").isdecimal():
        parts.append(f"memory {int(values['MemoryCurrent']) // _MIB} MiB")
    return f" — {', '.join(parts)}" if parts else ""


def _since(holder: dict) -> str:
    try:
        return f", since {datetime.fromisoformat(holder['at']):%Y-%m-%d %H:%M} UTC"
    except (KeyError, TypeError, ValueError):
        return ""


def worker_status_lines(inst: Installation) -> list[str]:
    """One line per running worker (kind, unit, pid, start time in UTC, usage), or one saying
    none run."""
    holders = [h for h in live_holders(inst.locks_dir) if isinstance(h.get("branch"), str)]
    if not holders:
        return ["workers: none running"]
    return [
        f"worker build {unit}: pid {holder['pid']}{_since(holder)}{_usage(inst, unit)}"
        for holder in holders
        for unit in [holder["branch"].split("/", 1)[-1]]
    ]
