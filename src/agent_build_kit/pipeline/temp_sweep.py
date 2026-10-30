"""The sweep at the start of a tick of what a killed unit-test run left in `runs/tmp/pytest`."""

from __future__ import annotations

import os
import shutil
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.file_lock import proc_identity, same_process

# The file in a run's folder that names the process the run belongs to: its id on the first line
# and, on the second, when it began (the pair names one process; a pid alone can be reused).
PID_FILE = "pid"


def write_pid_file(folder: Path) -> None:
    """Record the running process in `folder`, for the sweep to judge the folder by."""
    pid = os.getpid()
    (folder / PID_FILE).write_text(f"{pid}\n{proc_identity(pid) or ''}\n")


def sweep_temp_folders(
    installation: Installation,
    *,
    now: datetime,
    alive: Callable[[int, str | None], bool] = same_process,
    remove: Callable[[Path], None] = shutil.rmtree,
    log: Callable[[str], None],
) -> list[Path]:
    """Remove the run folders of `runs/tmp/pytest` older than `global_limits.temp_keep_hours`
    whose pid file names a process that is not alive; return the folders removed. A folder that
    cannot be removed is logged and left, and nothing outside `runs/tmp/pytest` is touched."""
    root = installation.pytest_temp_root
    oldest = now.timestamp() - installation.config.global_limits.temp_keep_hours * 3600
    removed: list[Path] = []
    try:
        folders = sorted(path for path in root.iterdir() if path.is_dir() and not path.is_symlink())
    except FileNotFoundError:
        return removed
    except OSError as error:
        log(f"temp sweep: {root} could not be read: {error}")
        return removed
    for folder in folders:
        try:
            if folder.stat().st_mtime > oldest or _run_alive(folder, alive):
                continue
            remove(folder)
        except OSError as error:
            log(f"temp sweep: {folder} was not removed: {error}")
            continue
        removed.append(folder)
    return removed


def _run_alive(folder: Path, alive: Callable[[int, str | None], bool]) -> bool:
    """Whether the folder's pid file names a running process; no readable pid file counts as
    dead, and a file without a start time is judged by the pid alone."""
    try:
        lines = (folder / PID_FILE).read_text().splitlines()
        return alive(int(lines[0]), (lines[1].strip() or None) if len(lines) > 1 else None)
    except (OSError, ValueError, IndexError):
        return False
