"""The base's selection data is recorded by a full unit-test run that holds a unit-test slot behind
every unit's check (spec: selection-data-comes-from-the-base). A small real git project is the
base and the real python-uv profile makes the commands; the command runner is the faked boundary,
writing the data file the recording command names."""

from __future__ import annotations

import subprocess
import threading
from contextlib import ExitStack
from datetime import UTC, datetime
from pathlib import Path

import pytest

from agent_build_kit.pipeline.selection_base import (
    RECORDING_HOLDER,
    BaseRecording,
    kept_recordings,
    record_base_data,
)
from agent_build_kit.pipeline.shell import git_out
from agent_build_kit.pipeline.unit_test_slots import unit_test_slot
from agent_build_kit.profiles.python_uv import PythonUvProfile
from tests.selection_base_fakes import BaseRepo
from tests.unit_test_slot_fakes import waiting_run, waiting_units
from tests.waiting import wait_for

NOW = datetime(2026, 11, 8, 9, 0, tzinfo=UTC)
DATA_FILE = "TESTMON_DATAFILE="


class Runner:
    """The command runner: notes each command and where it ran, and writes the data file the
    recording command names. `order` is shared with the unit checks of a test."""

    def __init__(self, order: list[str] | None = None, exit_code: int = 0) -> None:
        self.order = order if order is not None else []
        self.exit_code = exit_code
        self.ran: list[tuple[list[str], Path, str]] = []

    def __call__(self, command: list[str], *, cwd: Path) -> subprocess.CompletedProcess:
        head = git_out(cwd, "rev-parse", "HEAD")
        self.ran.append((command, cwd, head))
        self.order.append("recording")
        for word in command:
            if word.startswith(DATA_FILE):
                Path(word.removeprefix(DATA_FILE)).write_text(f"data@{head}")
        return subprocess.CompletedProcess(command, self.exit_code, "", "")


class Setup:
    def __init__(self, tmp_path: Path) -> None:
        self.base = BaseRepo(tmp_path / "app")
        self.store = tmp_path / "state" / "selection-base"
        self.locks = tmp_path / "locks"
        self.errors: list[BaseException] = []

    def record(self, run: Runner, *, limit: int | None = 1) -> BaseRecording | None:
        return record_base_data(
            store=self.store,
            repo=self.base.repo,
            base="main",
            profile=PythonUvProfile(),
            run=run,
            locks_dir=self.locks,
            limit=limit,
            kept=3,
            max_age_hours=12,
            now=lambda: NOW,
        )

    def in_thread(self, run: Runner) -> threading.Thread:
        def go() -> None:
            try:
                self.record(run)
            except BaseException as error:  # noqa: BLE001 - handed to the test thread
                self.errors.append(error)

        thread = threading.Thread(target=go, daemon=True)
        thread.start()
        return thread


@pytest.fixture
def setup(tmp_path: Path) -> Setup:
    return Setup(tmp_path)


def test_the_recording_is_the_profiles_full_run_of_a_checkout_of_the_bases_tip(
    setup: Setup,
) -> None:
    setup.base.move()
    tip = setup.base.tip()
    run = Runner()

    made = setup.record(run)

    assert made is not None and made.commit == tip
    (command, where, head) = run.ran[0]
    assert head == tip and where != setup.base.repo
    assert any(word.startswith(DATA_FILE) for word in command)
    assert "--testmon-forceselect" not in command
    assert made.path.read_text() == f"data@{tip}"
    assert [r.commit for r in kept_recordings(setup.store)] == [tip]


def test_the_checkout_the_recording_ran_in_is_removed(setup: Setup) -> None:
    run = Runner()

    setup.record(run)

    assert not run.ran[0][1].exists()
    assert len(git_out(setup.base.repo, "worktree", "list").splitlines()) == 1


def test_a_failed_recording_run_keeps_nothing_and_removes_its_checkout(setup: Setup) -> None:
    run = Runner(exit_code=1)

    with pytest.raises(RuntimeError, match="recording run"):
        setup.record(run)

    assert kept_recordings(setup.store) == []
    assert not list(setup.store.glob("*.tmp"))
    assert not run.ran[0][1].exists()


def test_nothing_is_run_and_no_slot_taken_when_the_base_is_already_recorded(setup: Setup) -> None:
    setup.record(Runner())
    run = Runner()

    assert setup.record(run) is None

    assert run.ran == []


def test_a_unit_check_is_served_before_a_recording_that_began_waiting_first(
    setup: Setup,
) -> None:
    order: list[str] = []
    run = Runner(order)
    with ExitStack() as stack:
        with unit_test_slot(setup.locks, 1, holder="holder/1"):
            recording = setup.in_thread(run)
            wait_for(lambda: RECORDING_HOLDER in waiting_units(setup.locks), what="the recording")
            check = stack.enter_context(
                waiting_run(setup.locks, "unit/1", rank=(2, 4), order=order)
            )
            check.until_waiting(setup.locks, "unit/1")
        wait_for(lambda: len(order) == 1, what="the first run to take the slot")
        assert order == ["unit/1"], "the recording ran ahead of the unit's check"
        check.release.set()
        recording.join(timeout=20)

    assert order == ["unit/1", "recording"]
    assert setup.errors == []


def test_a_second_refresh_that_waited_behind_the_first_makes_no_new_recording(
    setup: Setup,
) -> None:
    first, second = Runner(), Runner()
    with unit_test_slot(setup.locks, 1, holder="holder/1"):
        threads = [setup.in_thread(first)]
        wait_for(lambda: waiting_units(setup.locks) == [RECORDING_HOLDER], what="the first")
        threads.append(setup.in_thread(second))
        wait_for(lambda: len(waiting_units(setup.locks)) == 2, what="the second")
    for thread in threads:
        thread.join(timeout=20)

    assert setup.errors == []
    assert len(first.ran) + len(second.ran) == 1
    assert len(kept_recordings(setup.store)) == 1
