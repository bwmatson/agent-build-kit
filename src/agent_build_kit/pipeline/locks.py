"""Process identity shared by the branch lock and the leases."""

from __future__ import annotations

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
