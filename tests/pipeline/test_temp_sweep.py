"""The sweep at the start of a tick removes the run folders of `<planning home>/tmp/pytest` that
are old and whose process is gone, and nothing else (spec: test-temp-folders-clean-up)."""

from __future__ import annotations

import os
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.temp_sweep import PID_FILE, sweep_temp_folders, write_pid_file
from tests.conftest import make_installation

NOW = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)
DEAD = 4_000_001
LIVE = 4_000_002


STARTED = "1000"


def run_folder(
    installation: Installation,
    name: str,
    *,
    pid: int,
    age_hours: float,
    started: str | None = STARTED,
) -> Path:
    folder = installation.pytest_temp_root / name
    (folder / "pytest-of-user" / "pytest-0").mkdir(parents=True)
    (folder / PID_FILE).write_text(f"{pid}\n{started}\n" if started else str(pid))
    stamp = (NOW - timedelta(hours=age_hours)).timestamp()
    os.utime(folder, (stamp, stamp))
    return folder


def alive(pid: int, started: str | None) -> bool:
    """LIVE runs, and began at STARTED; a record with no start time is judged by the pid."""
    return pid == LIVE and started in (None, STARTED)


def sweep(installation: Installation, messages: list[str], **kw) -> list[Path]:
    return sweep_temp_folders(installation, now=NOW, alive=alive, log=messages.append, **kw)


def test_an_old_folder_of_a_dead_process_is_removed(installation: Installation) -> None:
    folder = run_folder(installation, "feature-1-a", pid=DEAD, age_hours=30)

    removed = sweep(installation, [])

    assert not folder.exists()
    assert removed == [folder]


def test_a_folder_of_a_live_process_is_kept_however_old(installation: Installation) -> None:
    folder = run_folder(installation, "feature-1-a", pid=LIVE, age_hours=300)

    sweep(installation, [])

    assert folder.is_dir()


def test_a_folder_whose_pid_was_reused_by_another_process_is_removed(
    installation: Installation,
) -> None:
    folder = run_folder(installation, "feature-1-a", pid=LIVE, age_hours=30, started="999")

    sweep(installation, [])

    assert not folder.exists()


def test_a_pid_file_without_a_start_time_is_judged_by_the_pid_alone(
    installation: Installation,
) -> None:
    live = run_folder(installation, "feature-1-a", pid=LIVE, age_hours=30, started=None)
    dead = run_folder(installation, "feature-1-b", pid=DEAD, age_hours=30, started=None)

    sweep(installation, [])

    assert live.is_dir()
    assert not dead.exists()


def test_the_pid_file_a_run_writes_names_this_process_and_is_kept_by_the_sweep(
    installation: Installation,
) -> None:
    folder = run_folder(installation, "feature-1-a", pid=DEAD, age_hours=30)
    write_pid_file(folder)

    assert sweep_temp_folders(installation, now=NOW, log=print) == []
    assert folder.is_dir()


def test_a_folder_younger_than_the_limit_is_kept_though_its_process_is_gone(
    installation: Installation,
) -> None:
    folder = run_folder(installation, "feature-1-a", pid=DEAD, age_hours=23)

    sweep(installation, [])

    assert folder.is_dir()


def test_the_limit_is_global_limits_temp_keep_hours(tmp_path: Path) -> None:
    short = make_installation(tmp_path, global_limits={"temp_keep_hours": 2})
    folder = run_folder(short, "feature-1-a", pid=DEAD, age_hours=3)

    sweep(short, [])

    assert not folder.exists()


def test_nothing_outside_the_pytest_temp_root_is_touched(installation: Installation) -> None:
    runs = installation.state_dir
    beside = runs / "tmp" / "other" / "old"
    beside.mkdir(parents=True)
    state = runs / "units.json"
    state.write_text("{}")
    long_ago = (NOW - timedelta(days=30)).timestamp()
    for path in (beside, state):
        os.utime(path, (long_ago, long_ago))
    old = run_folder(installation, "feature-1-a", pid=DEAD, age_hours=30)

    sweep(installation, [])

    assert not old.exists()
    assert beside.is_dir()
    assert state.is_file()


def test_a_missing_pytest_temp_root_is_not_an_error(installation: Installation) -> None:
    assert sweep(installation, []) == []


def test_a_failing_removal_is_logged_and_the_other_folders_are_still_swept(
    installation: Installation,
) -> None:
    stuck = run_folder(installation, "feature-1-a", pid=DEAD, age_hours=30)
    other = run_folder(installation, "feature-1-b", pid=DEAD, age_hours=30)
    messages: list[str] = []

    def remove(path: Path) -> None:
        if path == stuck:
            raise OSError("device busy")
        shutil.rmtree(path)

    removed = sweep(installation, messages, remove=remove)

    assert stuck.is_dir()
    assert not other.exists()
    assert removed == [other]
    assert any("device busy" in line and "feature-1-a" in line for line in messages)


def test_a_failing_removal_does_not_raise(installation: Installation) -> None:
    folder = run_folder(installation, "feature-1-a", pid=DEAD, age_hours=30)
    messages: list[str] = []

    def remove(path: Path) -> None:
        raise PermissionError("denied")

    removed = sweep(installation, messages, remove=remove)

    assert removed == []
    assert folder.is_dir()
    assert any("denied" in line for line in messages)
