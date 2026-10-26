"""Process identity shared by the branch lock and the leases."""

from __future__ import annotations

import os
from pathlib import Path


def proc_identity(pid: int) -> str | None:
    """When the process began, in the kernel's ticks, or None if there is no such process.
    The pair (pid, identity) names one process for good; a pid alone can be reused."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
    except OSError:
        return None
    # The command name, in parentheses, may itself hold spaces and parentheses.
    return stat[stat.rindex(")") + 2 :].split()[19]


def process_alive(pid: int) -> bool:
    """Whether a process with this id exists: another user's counts as alive. Branch locks
    and the e2e-test lock both judge a recorded holder by it."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # Someone else's process, but alive.
    return True


def holder_alive(pid: int, started: str | None) -> bool:
    """Whether the process a lock or lease names still holds it. A recorded start time is
    compared with the process's own, so a reused pid is not the holder. A host that cannot
    read start times records none, and then only whether the pid lives can be judged."""
    if started is None:
        return process_alive(pid)
    current = proc_identity(pid)
    return process_alive(pid) if current is None else current == started
