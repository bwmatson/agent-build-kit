"""The base's selection data is recorded by a full unit-test run that holds a unit-test slot behind
every unit's check (spec: selection-data-comes-from-the-base). A small real git project is the
base and the real python-uv profile makes the commands; the command runner is the faked boundary,
writing the data file the recording command names."""

from __future__ import annotations

import subprocess
import threading
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from datetime import UTC, datetime
from pathlib import Path

import pytest

from agent_build_kit.pipeline.selection_base import (
    RECORDING_HOLDER,
    BaseRecording,
    kept_recordings,
    record_base_data,
)
from agent_build_kit.pipeline.shell import git, git_out
from agent_build_kit.pipeline.unit_test_slots import LEAST_URGENT, unit_test_slot
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

    @contextmanager
    def in_thread(self, run: Runner, *, limit: int | None = 1) -> Iterator[threading.Thread]:
        """A refresh on a thread of its own, joined when the block ends."""

        def go() -> None:
            try:
                self.record(run, limit=limit)
            except BaseException as error:  # noqa: BLE001 - handed to the test thread
                self.errors.append(error)

        thread = threading.Thread(target=go, daemon=True)
        thread.start()
        try:
            yield thread
        finally:
            thread.join(timeout=20)


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


def test_a_run_that_crashed_or_left_a_checkout_of_the_tip_does_not_stop_the_next_recording(
    setup: Setup,
) -> None:
    class Crash(Exception):
        pass

    def crashes(command: list[str], *, cwd: Path) -> subprocess.CompletedProcess:
        raise Crash("the run was cut short")

    leftover = setup.store.parent / "leftover"
    git(setup.base.repo, "worktree", "add", "--detach", str(leftover), setup.base.tip())
    with pytest.raises(Crash):
        setup.record(crashes)  # type: ignore[arg-type]
    assert len(git_out(setup.base.repo, "worktree", "list").splitlines()) == 2

    made = setup.record(Runner())

    assert made is not None and made.commit == setup.base.tip()


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

    with unit_test_slot(setup.locks, 1, holder="holder/1"):
        # the only slot is held: a recording that queued for it would wait here forever
        assert setup.record(run) is None
        assert waiting_units(setup.locks) == []

    assert run.ran == []


@pytest.mark.parametrize("rank", [(2, 4), LEAST_URGENT], ids=["start-key", "least-urgent"])
def test_a_unit_check_is_served_before_a_recording_that_began_waiting_first(
    setup: Setup, rank: tuple[int, ...]
) -> None:
    order: list[str] = []
    run = Runner(order)
    with ExitStack() as stack:
        with unit_test_slot(setup.locks, 1, holder="holder/1"):
            stack.enter_context(setup.in_thread(run))
            wait_for(lambda: RECORDING_HOLDER in waiting_units(setup.locks), what="the recording")
            check = stack.enter_context(waiting_run(setup.locks, "unit/1", rank=rank, order=order))
            check.until_waiting(setup.locks, "unit/1")
        wait_for(lambda: len(order) == 1, what="the first run to take the slot")
        assert order == ["unit/1"], "the recording ran ahead of the unit's check"
        check.release.set()

    assert order == ["unit/1", "recording"]
    assert setup.errors == []


class BlockingRunner(Runner):
    """A runner that says it has started and holds its run until told to go on."""

    def __init__(self) -> None:
        super().__init__()
        self.started = threading.Event()
        self.go_on = threading.Event()

    def __call__(self, command: list[str], *, cwd: Path) -> subprocess.CompletedProcess:
        self.started.set()
        self.go_on.wait(timeout=20)
        return super().__call__(command, cwd=cwd)


@pytest.mark.parametrize("limit", [None, 2], ids=["no-limit", "room-for-both"])
def test_a_refresh_that_finds_another_recording_the_base_returns_at_once_and_runs_nothing(
    setup: Setup, limit: int | None
) -> None:
    first, second = BlockingRunner(), Runner()
    with setup.in_thread(first, limit=limit):
        wait_for(first.started.is_set, what="the first recording to start")

        assert setup.record(second, limit=limit) is None

        first.go_on.set()

    assert setup.errors == []
    assert second.ran == []
    assert len(first.ran) == 1
    assert len(kept_recordings(setup.store)) == 1
    assert not list(setup.store.glob("*.tmp"))


def test_the_next_refresh_removes_what_a_cut_short_one_left_in_the_store(setup: Setup) -> None:
    setup.store.mkdir(parents=True)
    (setup.store / ("a" * 40 + ".data")).write_text("orphan")
    (setup.store / ("b" * 40 + ".json")).write_text("{}")
    (setup.store / ("c" * 40 + ".data.tmp")).write_text("partial")

    made = setup.record(Runner())

    assert made is not None
    assert sorted(p.name for p in setup.store.iterdir()) == [
        f"{made.commit}.data",
        f"{made.commit}.json",
    ]
