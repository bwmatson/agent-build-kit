"""The tick's temp sweep runs in the background: a ready unit's build starts without waiting for
it, the tick waits for it (with a bound) before it returns, and a failure in it never fails the
tick (spec: temp-folder-reporting)."""

from __future__ import annotations

import os
import shutil
import threading
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.stack_runner import RunOutcome
from agent_build_kit.pipeline.temp_sweep import sweep_temp_folders
from agent_build_kit.pipeline.unit_store import UnitStore
from tests.pipeline import test_cli_pipeline as base
from tests.pipeline.test_cli_pipeline import (  # noqa: F401 — fixtures
    argv_namespace,
    healthy,
    isolated,
    stored,
)
from tests.pipeline.test_temp_sweep import run_folder
from tests.time_limit import LOADED_TEST_TIME_LIMIT

# The tests of this module run whole passes, whose time depends on the machine's load.
pytestmark = [
    pytest.mark.usefixtures("scripted_engine"),
    pytest.mark.time_limit(LOADED_TEST_TIME_LIMIT),
]

OLD = 300
# A safety net only: a test that works never waits this long.
GIVE_UP = 10


class Builds:
    """A runner that notes whether the sweep had finished when the build began, then lets the
    sweep's slow removal go on. `swept` fills when a removal ends."""

    def __init__(self, release: threading.Event, swept: list[Path]) -> None:
        self.release = release
        self.swept = swept
        self.sweep_done_at_start: list[bool] = []

    def run(self, unit, *, base, graph):
        self.sweep_done_at_start.append(bool(self.swept))
        self.release.set()
        return RunOutcome(status="open", detail="opened #1", pr=1)


def sweeping_with(monkeypatch: pytest.MonkeyPatch, remove: Callable[[Path], None]) -> list[str]:
    """The tick's sweep, with `remove` as its remove; return the messages the tick logs."""
    real = sweep_temp_folders
    messages: list[str] = []
    monkeypatch.setattr(cli, "log", lambda message, **_: messages.append(message))

    def sweep(inst: Installation, *, now: datetime, log: Callable[[str], None]) -> list[Path]:
        return real(inst, now=now, remove=remove, log=log)

    monkeypatch.setattr(cli, "sweep_temp_folders", sweep)
    return messages


def test_a_ready_units_build_starts_before_the_sweep_has_finished(
    healthy,  # noqa: F811 — fixture
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    UnitStore(tmp_path / "units.json").upsert([stored()])
    folder = run_folder(base.inst, "a1b2c3d4", pid=4_000_001, age_hours=OLD)
    release = threading.Event()
    swept: list[Path] = []

    def slow_remove(path: Path) -> None:
        release.wait(GIVE_UP)
        shutil.rmtree(path)
        swept.append(path)

    messages = sweeping_with(monkeypatch, slow_remove)
    runner = Builds(release, swept)
    monkeypatch.setattr(cli, "build_runner", lambda unit, **kwargs: runner)

    assert cli.cmd_tick(argv_namespace(dry_run=False), base.inst) == 0

    assert runner.sweep_done_at_start == [False]
    assert not folder.exists()
    assert any(message.startswith("temp sweep: removed a1b2c3d4") for message in messages)


def test_the_tick_waits_for_the_sweep_before_it_returns(
    healthy,  # noqa: F811 — fixture
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    UnitStore(tmp_path / "units.json").upsert([stored()])
    folders = [
        run_folder(base.inst, name, pid=4_000_001, age_hours=OLD)
        for name in ("a1b2c3d4", "b1b2c3d4", "c1b2c3d4")
    ]
    release = threading.Event()
    swept: list[Path] = []

    def slow_remove(path: Path) -> None:
        release.wait(GIVE_UP)
        shutil.rmtree(path)
        swept.append(path)

    sweeping_with(monkeypatch, slow_remove)
    runner = Builds(release, swept)
    monkeypatch.setattr(cli, "build_runner", lambda unit, **kwargs: runner)

    assert cli.cmd_tick(argv_namespace(dry_run=False), base.inst) == 0

    assert runner.sweep_done_at_start == [False]
    assert sorted(swept) == sorted(folders)
    assert not any(folder.exists() for folder in folders)


def test_a_folder_left_half_removed_is_finished_by_the_next_ticks_sweep(
    healthy,  # noqa: F811 — fixture
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    UnitStore(tmp_path / "units.json").upsert([stored()])
    folder = run_folder(base.inst, "a1b2c3d4", pid=4_000_001, age_hours=OLD)
    release = threading.Event()
    ended: list[Path] = []

    def half_remove(path: Path) -> None:
        release.wait(GIVE_UP)
        try:
            shutil.rmtree(path / "pytest-of-user")
            raise OSError("interrupted")
        finally:
            ended.append(path)

    messages = sweeping_with(monkeypatch, half_remove)
    runner = Builds(release, ended)
    monkeypatch.setattr(cli, "build_runner", lambda unit, **kwargs: runner)
    assert cli.cmd_tick(argv_namespace(dry_run=False), base.inst) == 0
    assert runner.sweep_done_at_start == [False]
    assert folder.is_dir()
    assert any("a1b2c3d4 was not removed" in message for message in messages)

    # Removing a child touched the folder; it is old again when the next tick looks at it.
    os.utime(folder, (0, 0))
    # A tick with nothing to do exits before the sweep, so the next one has a unit to build.
    UnitStore(tmp_path / "units.json").upsert([stored("add-marker/2")])
    sweeping_with(monkeypatch, shutil.rmtree)
    assert cli.cmd_tick(argv_namespace(dry_run=False), base.inst) == 0

    assert not folder.exists()


def test_a_sweep_that_raises_is_logged_and_the_tick_completes_its_builds(
    healthy,  # noqa: F811 — fixture
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    UnitStore(tmp_path / "units.json").upsert([stored()])
    built = threading.Event()

    class Runner:
        def run(self, unit, *, base, graph):
            built.set()
            return RunOutcome(status="open", detail="opened #1", pr=1)

    messages: list[str] = []
    monkeypatch.setattr(cli, "log", lambda message, **_: messages.append(message))

    def explode(inst, **kwargs):
        raise RuntimeError("sweep exploded")

    monkeypatch.setattr(cli, "sweep_temp_folders", explode)
    monkeypatch.setattr(cli, "build_runner", lambda unit, **kwargs: Runner())

    assert cli.cmd_tick(argv_namespace(dry_run=False), base.inst) == 0

    assert built.is_set()
    assert any("sweep exploded" in message for message in messages)
