"""A unit that meets a test whose agent run is in flight takes the open change and waits on it; it
does not wait for the lock of the test, which a run holds for minutes (spec: regression-agent).

The lock is held by the test itself, as the run of another unit holds it: no thread, no sleep.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import ExitStack

import pytest

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.file_lock import LockTimeout, file_lock
from agent_build_kit.pipeline.flakes import fix_change_name, flake_change_name
from agent_build_kit.pipeline.work_graph import FIX_PREFIX
from tests.pipeline.test_flake_fix_change import change_with_unit, code_repo, flaked, waits_on
from tests.regression_agent_fakes import DefaultAgent, waited_on
from tests.regression_agent_support import TEST, write_change


def run_in_flight(installation: Installation, *, with_tasks: bool):
    """The lock of the test, held, and the folder of the change the run made."""
    fix = flake_change_name(TEST)
    folder = installation.changes_dir / fix
    if with_tasks:
        write_change(folder)
    else:
        folder.mkdir(parents=True)  # made at the start of a run, before it has written
    lock = installation.state_dir / f"regression-{fix_change_name(TEST, FIX_PREFIX)}.lock"
    return fix, file_lock(lock)


@pytest.mark.parametrize("with_tasks", [True, False], ids=["written", "being-written"])
def test_a_second_unit_takes_the_open_change_while_the_lock_is_held_and_runs_nothing(
    installation: Installation, no_real_regression_agent: DefaultAgent, with_tasks: bool
) -> None:
    code_repo(installation)
    unit = change_with_unit(installation, "feature", "feature/1")
    fix, held = run_in_flight(installation, with_tasks=with_tasks)

    with held:
        named = waited_on(installation, flaked(), unit)

    assert named == fix
    assert waits_on(installation, "feature") == [fix]
    assert no_real_regression_agent.runtime.requests == []


class PausingClock:
    """A clock whose pause runs `during` and moves time on; it never sleeps."""

    def __init__(self, during: Callable[[], None]) -> None:
        self.during = during
        self.now = 0.0
        self.pauses = 0

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float, /) -> None:
        self.pauses += 1
        self.now += seconds
        self.during()


def test_a_unit_that_finds_no_folder_yet_waits_on_the_one_that_appears(
    installation: Installation, no_real_regression_agent: DefaultAgent
) -> None:
    code_repo(installation)
    unit = change_with_unit(installation, "feature", "feature/1")
    fix = flake_change_name(TEST)
    lock = installation.state_dir / f"regression-{fix_change_name(TEST, FIX_PREFIX)}.lock"

    with file_lock(lock):
        clock = PausingClock(lambda: write_change(installation.changes_dir / fix))
        named = waited_on(installation, flaked(), unit, clock=clock)

    assert named == fix
    assert clock.pauses == 1
    assert waits_on(installation, "feature") == [fix]
    assert no_real_regression_agent.runtime.requests == []


def test_a_unit_runs_the_agent_once_when_the_lock_is_freed_while_it_waits(
    installation: Installation, no_real_regression_agent: DefaultAgent
) -> None:
    code_repo(installation)
    unit = change_with_unit(installation, "feature", "feature/1")
    lock = installation.state_dir / f"regression-{fix_change_name(TEST, FIX_PREFIX)}.lock"
    with ExitStack() as stack:
        stack.enter_context(file_lock(lock))
        clock = PausingClock(stack.pop_all().close)

        named = waited_on(installation, flaked(), unit, clock=clock)

    assert named == flake_change_name(TEST)
    assert len(no_real_regression_agent.runtime.requests) == 1


def test_a_lock_held_with_no_folder_for_good_times_out_instead_of_hanging(
    installation: Installation, no_real_regression_agent: DefaultAgent
) -> None:
    code_repo(installation)
    unit = change_with_unit(installation, "feature", "feature/1")
    lock = installation.state_dir / f"regression-{fix_change_name(TEST, FIX_PREFIX)}.lock"

    with file_lock(lock), pytest.raises(LockTimeout):
        waited_on(installation, flaked(), unit, clock=PausingClock(lambda: None))

    assert no_real_regression_agent.runtime.requests == []
