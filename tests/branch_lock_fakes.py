"""A branch lock naming a chosen process, and a process id that belongs to none."""

from __future__ import annotations

import json
import subprocess
import sys

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.workspaces import branch_lock


def dead_pid() -> int:
    """The id of a process that has exited."""
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    child.wait()
    return child.pid


def lock_held_by(inst: Installation, branch: str, pid: int) -> None:
    """The lock file `branch_lock` writes, naming `pid` as its holder."""
    locks = inst.state_dir / "locks"
    before = set(locks.glob("*.lock")) if locks.exists() else set()
    with branch_lock(branch, root=locks):
        (made,) = set(locks.glob("*.lock")) - before
    made.write_text(json.dumps({"pid": pid, "branch": branch, "at": "2030-01-01T09:00:00+00:00"}))
