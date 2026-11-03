"""The slots a whole-suite unit-test run takes (spec: unit-test-concurrency): one lock file per
slot in the planning repo's lock folder, taken without waiting when one is free, polled for when
they are all taken, freed by the kernel when the holder's process ends, and each naming its
holder."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from contextlib import ExitStack
from pathlib import Path

import pytest
from agent_build_kit.pipeline.unit_test_slots import slot_path, unit_test_slot

from agent_build_kit.pipeline.e2e import read_lock_record
from agent_build_kit.pipeline.file_lock import POLL_SECONDS
from tests.waiting import wait_for


class FakeClock:
    """Time that passes only when the wait sleeps; `on_sleep` runs at each sleep."""

    def __init__(self, on_sleep=None, *, step: float = 0.0) -> None:
        self.now = 0.0
        self.step = step
        self.sleeps: list[float] = []
        self.on_sleep = on_sleep

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float, /) -> None:
        self.sleeps.append(seconds)
        self.now += seconds + self.step
        if self.on_sleep is not None:
            self.on_sleep(len(self.sleeps))


def test_with_no_limit_nothing_waits_and_no_slot_file_is_made(tmp_path: Path) -> None:
    with unit_test_slot(tmp_path / "locks", None, holder="a/1") as waited:
        assert waited == 0.0

    assert not (tmp_path / "locks").exists()


def test_two_holders_of_a_limit_of_two_get_different_slots_and_each_names_itself(
    tmp_path: Path,
) -> None:
    with ExitStack() as held:
        held.enter_context(unit_test_slot(tmp_path, 2, holder="a/1"))
        held.enter_context(unit_test_slot(tmp_path, 2, holder="b/1"))

        records = [read_lock_record(slot_path(tmp_path, i).read_text()) for i in (1, 2)]

    assert [r.unit for r in records if r is not None] == ["a/1", "b/1"]
    assert all(r is not None and r.pid == os.getpid() and r.since and r.host for r in records)


def test_a_third_run_waits_and_takes_the_slot_a_holder_frees(tmp_path: Path) -> None:
    told: list[str] = []
    first = ExitStack()
    first.enter_context(unit_test_slot(tmp_path, 2, holder="a/1"))
    second = unit_test_slot(tmp_path, 2, holder="b/1")
    second.__enter__()
    clock = FakeClock(on_sleep=lambda count: first.close() if count == 3 else None)

    with unit_test_slot(tmp_path, 2, holder="c/1", on_wait=told.append, clock=clock) as waited:
        assert waited == pytest.approx(sum(clock.sleeps))
        assert waited > 0
    second.__exit__(None, None, None)

    assert len(told) == 1
    assert "a/1" in told[0] and "b/1" in told[0]


def test_the_wait_polls_often_at_first_and_never_past_the_poll_interval(tmp_path: Path) -> None:
    holder = ExitStack()
    holder.enter_context(unit_test_slot(tmp_path, 1, holder="a/1"))
    clock = FakeClock(on_sleep=lambda count: holder.close() if count == 12 else None)

    with unit_test_slot(tmp_path, 1, holder="b/1", clock=clock):
        pass

    assert clock.sleeps[0] < clock.sleeps[-1]
    assert max(clock.sleeps) <= POLL_SECONDS


def test_a_wait_is_told_again_only_after_the_log_interval(tmp_path: Path) -> None:
    told: list[str] = []
    holder = ExitStack()
    holder.enter_context(unit_test_slot(tmp_path, 1, holder="a/1"))
    # Each sleep passes 30 s, so the interval passes after about ten of them.
    clock = FakeClock(on_sleep=lambda count: holder.close() if count == 15 else None, step=30.0)

    with unit_test_slot(tmp_path, 1, holder="b/1", on_wait=told.append, clock=clock):
        pass

    assert len(told) == 2


def test_the_slot_is_free_and_its_record_cleared_after_the_block(tmp_path: Path) -> None:
    with unit_test_slot(tmp_path, 1, holder="a/1"):
        pass

    assert slot_path(tmp_path, 1).read_text() == ""
    with unit_test_slot(tmp_path, 1, holder="b/1") as waited:
        assert waited == 0.0


def test_the_slot_is_released_when_the_block_raises(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError), unit_test_slot(tmp_path, 1, holder="a/1"):
        raise RuntimeError("the run failed")

    with unit_test_slot(tmp_path, 1, holder="b/1") as waited:
        assert waited == 0.0


def give_up_after_two(count: int) -> None:
    if count > 2:
        raise TimeoutError


HOLDER = """
import sys, time
from pathlib import Path
from agent_build_kit.pipeline.unit_test_slots import unit_test_slot
with unit_test_slot(Path(sys.argv[1]), 1, holder="child/1"):
    print("held", flush=True)
    time.sleep(60)
"""


def test_a_slot_whose_holder_process_is_killed_is_free_for_the_next_run(tmp_path: Path) -> None:
    child = subprocess.Popen(
        [sys.executable, "-c", HOLDER, str(tmp_path)], stdout=subprocess.PIPE, text=True
    )
    try:
        assert child.stdout is not None and child.stdout.readline().strip() == "held"
        busy = FakeClock(on_sleep=give_up_after_two)
        with pytest.raises(TimeoutError), unit_test_slot(tmp_path, 1, holder="a/1", clock=busy):
            pass
        child.kill()
        child.wait(timeout=10)

        began = time.monotonic()
        with unit_test_slot(tmp_path, 1, holder="a/1") as waited:
            assert waited < 5
        assert time.monotonic() - began < 5
    finally:
        child.kill()
        wait_for(lambda: child.poll() is not None, what="the holder to end")
