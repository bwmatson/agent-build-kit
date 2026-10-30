"""The sweep at the start of a tick of what a killed unit-test run left in the pytest temp root
(`Installation.pytest_temp_root`) and in the root it had before."""

from __future__ import annotations

import json
import os
import re
import shutil
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline import spans
from agent_build_kit.pipeline.file_lock import proc_identity, same_process

# The file in a run's folder that names the process the run belongs to: its id on the first line
# and, on the second, when it began (the pair names one process; a pid alone can be reused).
PID_FILE = "pid"
# The file that says which unit, run and tick a folder belongs to, since the folder's name is
# the run's token alone.
RUN_FILE = "run.json"
# A run folder of the current temp root is named by its run's token: 8 hex characters. Anything
# else in that root (a configured planning home's `tmp` may hold other things) is not the sweep's.
RUN_FOLDER = re.compile(r"[0-9a-f]{8}")


def write_pid_file(folder: Path) -> None:
    """Record the running process in `folder`, for the sweep to judge the folder by."""
    pid = os.getpid()
    (folder / PID_FILE).write_text(f"{pid}\n{proc_identity(pid) or ''}\n")


def write_run_file(folder: Path, unit: str, run: str) -> None:
    """Record whose folder this is, for a person who finds it and for the sweep's log."""
    record = {
        "unit": unit,
        "run": run,
        "tick": spans.PROCESS_TICK,
        "started": datetime.now(UTC).isoformat(),
        "pid": os.getpid(),
    }
    (folder / RUN_FILE).write_text(json.dumps(record) + "\n")


def sweep_temp_folders(
    installation: Installation,
    *,
    now: datetime,
    alive: Callable[[int, str | None], bool] = same_process,
    remove: Callable[[Path], None] = shutil.rmtree,
    log: Callable[[str], None],
) -> list[Path]:
    """Remove the run folders of the pytest temp root, and of the root it had before, that are
    older than `global_limits.temp_keep_hours` and whose pid file names a process that is not
    alive; return the folders removed. A removal is logged with the unit and start time its
    `run.json` names. A folder that cannot be removed is logged and left, and nothing outside the
    two roots is touched."""
    legacy = installation.legacy_pytest_temp_root
    removed: list[Path] = []
    for root, named in ((installation.pytest_temp_root, RUN_FOLDER), (legacy, None)):
        removed += _sweep_root(
            root,
            installation,
            now=now,
            alive=alive,
            remove=remove,
            log=log,
            skip=legacy,
            named=named,
        )
    return removed


def _sweep_root(
    root: Path,
    installation: Installation,
    *,
    now: datetime,
    alive: Callable[[int, str | None], bool],
    remove: Callable[[Path], None],
    log: Callable[[str], None],
    skip: Path,
    named: re.Pattern[str] | None,
) -> list[Path]:
    """The run folders of one root: those whose name matches `named`, or any when it is None.
    `skip` is the old root, which a configured planning home puts inside the new one: it is swept
    as a root, not judged as a run folder."""
    oldest = now.timestamp() - installation.config.global_limits.temp_keep_hours * 3600
    removed: list[Path] = []
    try:
        folders = sorted(
            path
            for path in root.iterdir()
            if path.is_dir()
            and not path.is_symlink()
            and path != skip
            and (named is None or named.fullmatch(path.name))
        )
    except FileNotFoundError:
        return removed
    except OSError as error:
        log(f"temp sweep: {root} could not be read: {error}")
        return removed
    for folder in folders:
        try:
            if folder.stat().st_mtime > oldest or _run_alive(folder, alive):
                continue
            whose = _whose(folder)
            remove(folder)
        except OSError as error:
            log(f"temp sweep: {folder} was not removed: {error}")
            continue
        log(f"temp sweep: removed {folder.name}{whose}")
        removed.append(folder)
    return removed


def _whose(folder: Path) -> str:
    """` (<unit>, started <time>)` from the folder's `run.json`; nothing for a folder of the old
    layout or one whose record cannot be read."""
    try:
        record = json.loads((folder / RUN_FILE).read_text())
        return f" ({record['unit']}, started {record['started']})"
    except (OSError, ValueError, KeyError, TypeError):
        return ""


def _run_alive(folder: Path, alive: Callable[[int, str | None], bool]) -> bool:
    """Whether the folder's pid file names a running process; no readable pid file counts as
    dead, and a file without a start time is judged by the pid alone."""
    try:
        lines = (folder / PID_FILE).read_text().splitlines()
        return alive(int(lines[0]), (lines[1].strip() or None) if len(lines) > 1 else None)
    except (OSError, ValueError, IndexError):
        return False
