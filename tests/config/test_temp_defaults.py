"""`global_limits.temp_keep_hours` defaults to 16 hours and `temp_warn_mb` keeps its default; a
sweep under the default keeps a run folder of 15 hours and removes one of 17 (spec:
temp-folder-reporting)."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

from agent_build_kit.config import LimitsConfig
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.temp_sweep import PID_FILE, sweep_temp_folders
from tests.conftest import make_installation

NOW = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)
DEAD = 4_000_001


def aged_run_folder(installation: Installation, name: str, hours: float) -> Path:
    folder = installation.pytest_temp_root / name
    folder.mkdir(parents=True)
    (folder / PID_FILE).write_text(f"{DEAD}\n1000\n")
    stamp = (NOW - timedelta(hours=hours)).timestamp()
    os.utime(folder, (stamp, stamp))
    return folder


def sweep(installation: Installation) -> list[Path]:
    return sweep_temp_folders(
        installation, now=NOW, alive=lambda pid, started: False, log=lambda message: None
    )


def test_the_default_limits_keep_sixteen_hours_and_warn_at_2048_megabytes() -> None:
    limits = LimitsConfig()

    assert limits.temp_keep_hours == 16
    assert limits.temp_warn_mb == 2048


def test_the_default_sweep_keeps_a_folder_of_15_hours_and_removes_one_of_17(
    installation: Installation,
) -> None:
    young = aged_run_folder(installation, "a1b2c3d4", 15)
    old = aged_run_folder(installation, "b1b2c3d4", 17)

    removed = sweep(installation)

    assert young.is_dir()
    assert not old.exists()
    assert removed == [old]


def test_a_configured_keep_time_wins_over_the_default(tmp_path: Path) -> None:
    configured = make_installation(tmp_path, global_limits={"temp_keep_hours": 30})
    folder = aged_run_folder(configured, "a1b2c3d4", 17)

    removed = sweep(configured)

    assert configured.config.global_limits.temp_keep_hours == 30
    assert LimitsConfig().temp_keep_hours == 16
    assert folder.is_dir()
    assert removed == []
