"""The sweep at the start of a tick of what a killed unit-test run left in the pytest temp root
(`Installation.pytest_temp_root`) and in the root it had before."""

from __future__ import annotations

import json
import os
import re
import shutil
import stat
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from agent_build_kit.installation import Installation
from agent_build_kit.model import Frozen
from agent_build_kit.pipeline import spans
from agent_build_kit.pipeline.file_lock import proc_identity, same_process

MEGABYTE = 1024 * 1024

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
    removed: list[Path] = []
    for root, named in _roots(installation):
        removed += _sweep_root(
            root, installation, now=now, alive=alive, remove=remove, log=log, named=named
        )
    return removed


def _roots(installation: Installation) -> tuple[tuple[Path, re.Pattern[str] | None], ...]:
    """The roots the sweep clears and `temp_size` measures, each with the pattern a run folder's
    name must match (None: any name). The old root's name is not a token, so a configured planning
    home that puts it inside the new root does not make it a run folder of that root."""
    return (
        (installation.pytest_temp_root, RUN_FOLDER),
        (installation.legacy_pytest_temp_root, None),
    )


def _run_folders(root: Path, named: re.Pattern[str] | None) -> list[Path]:
    """The run folders of `root`, sorted: real directories whose name matches `named`. An OSError
    reading the root propagates."""
    return sorted(
        path
        for path in root.iterdir()
        if path.is_dir() and not path.is_symlink() and (named is None or named.fullmatch(path.name))
    )


def _sweep_root(
    root: Path,
    installation: Installation,
    *,
    now: datetime,
    alive: Callable[[int, str | None], bool],
    remove: Callable[[Path], None],
    log: Callable[[str], None],
    named: re.Pattern[str] | None,
) -> list[Path]:
    """The run folders of one root that are old and whose process is gone, removed."""
    oldest = now.timestamp() - installation.config.global_limits.temp_keep_hours * 3600
    removed: list[Path] = []
    try:
        folders = _run_folders(root, named)
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


class TempSize(Frozen):
    """What the pytest temp roots hold: the run folders left in them, their size in bytes and the
    roots that hold any."""

    runs: int
    size: int
    warn: bool
    roots: tuple[Path, ...]

    @property
    def text(self) -> str:
        return f"{self.runs} run folder(s), {self.size / MEGABYTE:.1f} MB"


def temp_size(installation: Installation) -> TempSize | None:
    """The size of the run folders of the roots the sweep clears, or None when none of them can be
    read. A path that goes away or cannot be read while it is walked is skipped: a running
    unit-test step and a tick's sweep both delete from the roots."""
    runs = size = 0
    holding: list[Path] = []
    readable = False
    for root, named in _roots(installation):
        try:
            folders = _run_folders(root, named)
        except OSError:
            continue
        readable = True
        if folders:
            holding.append(root)
        runs += len(folders)
        size += sum(_bytes_in(folder) for folder in folders)
    if not readable:
        return None
    limit = installation.config.global_limits.temp_warn_mb
    return TempSize(runs=runs, size=size, warn=size > limit * MEGABYTE, roots=tuple(holding))


def _bytes_in(folder: Path) -> int:
    """The bytes of the regular files under `folder`, not following links."""
    total = 0
    for directory, _, names in os.walk(folder):
        for name in names:
            try:
                status = Path(directory, name).lstat()
            except OSError:
                continue
            if stat.S_ISREG(status.st_mode):
                total += status.st_size
    return total


def _run_alive(folder: Path, alive: Callable[[int, str | None], bool]) -> bool:
    """Whether the folder's pid file names a running process; no readable pid file counts as
    dead, and a file without a start time is judged by the pid alone."""
    try:
        lines = (folder / PID_FILE).read_text().splitlines()
        return alive(int(lines[0]), (lines[1].strip() or None) if len(lines) > 1 else None)
    except (OSError, ValueError, IndexError):
        return False
