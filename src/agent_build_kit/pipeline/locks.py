"""Process identity shared by the branch lock and the leases."""

from __future__ import annotations


def proc_identity(pid: int) -> str | None:
    """When the process began, or None if there is no such process. The pair (pid, identity)
    names one process for good; a pid alone can be reused."""
    raise NotImplementedError
