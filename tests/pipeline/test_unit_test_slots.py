"""The slots a whole-suite unit-test run takes (spec: unit-test-concurrency): one lock file per
slot in the planning repo's lock folder, taken without waiting when one is free, polled for when
they are all taken, freed by the kernel when the holder's process ends, and each naming its
holder."""

from __future__ import annotations

import fcntl
import json
import os
import subprocess
import sys
import time
from contextlib import ExitStack
from datetime import timedelta
from pathlib import Path

import pytest

from agent_build_kit.pipeline.e2e import read_lock_record
from agent_build_kit.pipeline.file_lock import POLL_SECONDS
from agent_build_kit.pipeline.unit_test_slots import slot_path, unit_test_slot
from tests.fake_clock import START, install
from tests.unit_test_slot_fakes import live_waiter, waiting_run, waiting_units
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


# Waiting runs are served in the order units start: by rank, then by when they began waiting.

URGENT = (0, 2)
LESS_URGENT = (2, 4)


def markers(locks: Path) -> list[Path]:
    return sorted(locks.glob("unit-test-waiting-*.lock"))


def declines(locks: Path, **options) -> None:
    """The run finds a free slot and does not take it: it polls until the clock gives up."""
    with pytest.raises(TimeoutError):
        with unit_test_slot(
            locks, 1, holder="new/1", clock=FakeClock(on_sleep=give_up_after_two), **options
        ):
            pytest.fail("the run took the slot")
    with slot_path(locks, 1).open("a+") as handle:  # the slot was left free
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)


def takes_at_once(locks: Path, **options) -> None:
    clock = FakeClock()
    with unit_test_slot(locks, 1, holder="new/1", clock=clock, **options) as waited:
        assert waited == 0.0
    assert clock.sleeps == []


@pytest.mark.parametrize(
    "urgent_first", [False, True], ids=["urgent-arrived-later", "urgent-first"]
)
def test_the_smaller_rank_takes_the_freed_slot_whatever_order_they_began_waiting(
    tmp_path: Path, urgent_first: bool
) -> None:
    order: list[str] = []
    began = [("urgent/1", URGENT), ("lazy/1", LESS_URGENT)]
    if not urgent_first:
        began.reverse()
    with ExitStack() as stack:
        runs = {}
        with unit_test_slot(tmp_path, 1, holder="holder/1"):
            for unit, rank in began:
                runs[unit] = stack.enter_context(
                    waiting_run(tmp_path, unit, rank=rank, order=order)
                )
                runs[unit].until_waiting(tmp_path, unit)
        wait_for(lambda: len(order) == 1, what="the first waiter to take the slot")
        assert order == ["urgent/1"]
        runs["urgent/1"].release.set()
        wait_for(lambda: len(order) == 2, what="the second waiter to take the slot")

    assert order == ["urgent/1", "lazy/1"]


def test_runs_of_equal_rank_are_served_in_the_order_they_began_waiting(tmp_path: Path) -> None:
    order: list[str] = []
    with ExitStack() as stack:
        runs = {}
        with unit_test_slot(tmp_path, 1, holder="holder/1"):
            # "z/1" began first; neither its name nor its marker's token puts it first
            for unit in ("z/1", "a/1"):
                runs[unit] = stack.enter_context(
                    waiting_run(tmp_path, unit, rank=LESS_URGENT, order=order)
                )
                runs[unit].until_waiting(tmp_path, unit)
        wait_for(lambda: len(order) == 1, what="the first waiter to take the slot")
        runs["z/1"].release.set()
        wait_for(lambda: len(order) == 2, what="the second waiter to take the slot")

    assert order == ["z/1", "a/1"]


def test_a_free_slot_is_not_taken_while_a_more_urgent_run_waits_that_has_not_polled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install(monkeypatch)
    with live_waiter(tmp_path, "1-aaaa", "urgent/1", since=START, rank=URGENT):
        declines(tmp_path, rank=LESS_URGENT)
        assert waiting_units(tmp_path) == ["urgent/1"]  # it left no marker of its own behind


def test_the_run_that_declined_takes_the_slot_once_the_waiter_is_gone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install(monkeypatch)
    waiter = ExitStack()
    waiter.enter_context(live_waiter(tmp_path, "1-aaaa", "urgent/1", since=START, rank=URGENT))
    clock = FakeClock(on_sleep=lambda count: waiter.close() if count == 2 else None)

    with unit_test_slot(tmp_path, 1, holder="new/1", rank=LESS_URGENT, clock=clock) as waited:
        assert waited == pytest.approx(sum(clock.sleeps))

    assert len(clock.sleeps) == 2


def test_a_run_more_urgent_than_the_waiters_takes_a_free_slot_at_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install(monkeypatch)
    with live_waiter(tmp_path, "1-aaaa", "lazy/1", since=START, rank=LESS_URGENT):
        takes_at_once(tmp_path, rank=URGENT)


def test_a_waiter_whose_process_ended_does_not_hold_anyone_back(tmp_path: Path) -> None:
    script = (
        "import sys\n"
        "from pathlib import Path\n"
        "from agent_build_kit.pipeline.unit_test_slots import unit_test_slot\n"
        "with unit_test_slot(Path(sys.argv[1]), 1, holder='ghost/1', rank=(0,),\n"
        "                    on_wait=lambda message: print('waiting', flush=True)):\n"
        "    pass\n"
    )
    holder = ExitStack()
    holder.enter_context(unit_test_slot(tmp_path, 1, holder="holder/1"))
    child = subprocess.Popen(
        [sys.executable, "-c", script, str(tmp_path)], stdout=subprocess.PIPE, text=True
    )
    try:
        assert child.stdout is not None and child.stdout.readline().strip() == "waiting"
        assert waiting_units(tmp_path) == ["ghost/1"]
        child.kill()
        child.wait(timeout=10)
        holder.close()

        assert waiting_units(tmp_path) == ["ghost/1"]  # the file is left, with nothing locking it
        takes_at_once(tmp_path, rank=LESS_URGENT)
    finally:
        child.kill()
        child.wait(timeout=10)


def test_a_marker_that_is_not_locked_is_ignored(tmp_path: Path, monkeypatch) -> None:
    install(monkeypatch)
    record = {"unit": "ghost/1", "pid": 1, "since": START.isoformat(), "rank": [0]}
    (tmp_path / "unit-test-waiting-1-dead.lock").write_text(json.dumps(record) + "\n")

    takes_at_once(tmp_path, rank=LESS_URGENT)


def test_with_a_free_slot_and_no_waiter_the_run_takes_it_at_once_and_makes_no_marker(
    tmp_path: Path,
) -> None:
    with unit_test_slot(tmp_path, 1, holder="a/1", rank=LESS_URGENT, clock=FakeClock()) as waited:
        assert waited == 0.0
        assert markers(tmp_path) == []

    assert markers(tmp_path) == []


def test_a_run_given_no_rank_is_served_after_a_run_given_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install(monkeypatch)
    with live_waiter(tmp_path, "1-aaaa", "late/1", since=START, rank=(9, 9, 9, 9)):
        declines(tmp_path)


def test_a_run_given_no_rank_that_began_waiting_first_is_served_after_one_given_a_rank(
    tmp_path: Path,
) -> None:
    order: list[str] = []
    with ExitStack() as stack:
        runs = {}
        with unit_test_slot(tmp_path, 1, holder="holder/1"):
            for unit, rank in (("unranked/1", None), ("ranked/1", (9, 9, 9, 9))):
                runs[unit] = stack.enter_context(
                    waiting_run(tmp_path, unit, rank=rank, order=order)
                )
                runs[unit].until_waiting(tmp_path, unit)
        wait_for(lambda: len(order) == 1, what="the first waiter to take the slot")
        assert order == ["ranked/1"]
        runs["ranked/1"].release.set()
        wait_for(lambda: len(order) == 2, what="the second waiter to take the slot")

    assert order == ["ranked/1", "unranked/1"]


def test_a_marker_without_a_rank_reads_as_least_urgent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install(monkeypatch)
    with live_waiter(tmp_path, "1-aaaa", "old/1", since=START - timedelta(hours=1), rank=None):
        takes_at_once(tmp_path, rank=(10**6, 10**6))


def test_a_run_with_no_rank_queues_behind_an_earlier_marker_without_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install(monkeypatch)
    with live_waiter(tmp_path, "1-aaaa", "old/1", since=START - timedelta(hours=1), rank=None):
        declines(tmp_path)


def test_runs_of_equal_rank_go_by_the_time_each_began_waiting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install(monkeypatch)
    with live_waiter(
        tmp_path, "1-aaaa", "first/1", since=START - timedelta(seconds=1), rank=LESS_URGENT
    ):
        declines(tmp_path, rank=LESS_URGENT)
    with live_waiter(
        tmp_path, "1-aaaa", "later/1", since=START + timedelta(seconds=1), rank=LESS_URGENT
    ):
        takes_at_once(tmp_path, rank=LESS_URGENT)


def test_runs_that_began_waiting_at_the_same_moment_go_by_the_marker_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install(monkeypatch)
    with live_waiter(tmp_path, "0-0000", "low-token/1", since=START, rank=LESS_URGENT):
        declines(tmp_path, rank=LESS_URGENT)
    with live_waiter(tmp_path, "zzzz-zzzz", "high-token/1", since=START, rank=LESS_URGENT):
        takes_at_once(tmp_path, rank=LESS_URGENT)


def test_the_marker_records_the_rank_beside_the_unit_pid_time_and_host(tmp_path: Path) -> None:
    seen: list[dict[str, object]] = []
    holder = ExitStack()
    holder.enter_context(unit_test_slot(tmp_path, 1, holder="a/1"))

    def look(count: int) -> None:
        if count == 1:
            [marker] = markers(tmp_path)
            seen.append(json.loads(marker.read_text()))
            holder.close()

    with unit_test_slot(tmp_path, 1, holder="b/1", rank=(1, 3, 1, 7), clock=FakeClock(look)):
        pass

    [record] = seen
    assert record["unit"] == "b/1" and record["rank"] == [1, 3, 1, 7]
    assert record["pid"] == os.getpid() and record["since"] and record["host"]


def test_two_waiters_of_two_slots_are_served_in_rank_order(tmp_path: Path) -> None:
    order: list[str] = []
    with ExitStack() as runs:
        with unit_test_slot(tmp_path, 2, holder="h/1"), unit_test_slot(tmp_path, 2, holder="h/2"):
            for unit, rank in (("lazy/1", LESS_URGENT), ("urgent/1", URGENT)):
                run = runs.enter_context(
                    waiting_run(tmp_path, unit, rank=rank, order=order, limit=2)
                )
                run.until_waiting(tmp_path, unit)
        wait_for(lambda: len(order) == 2, what="both waiters to take a slot")

    assert order[0] == "urgent/1"


def test_a_run_that_takes_a_slot_on_its_first_poll_behind_no_one_waited_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install(monkeypatch)
    told: list[str] = []
    with live_waiter(tmp_path, "1-aaaa", "lazy/1", since=START, rank=LESS_URGENT):
        with unit_test_slot(
            tmp_path, 1, holder="new/1", rank=URGENT, on_wait=told.append
        ) as waited:
            assert waited == 0.0

    assert told == []


def test_a_run_that_waits_only_for_a_waiter_ahead_says_so_and_names_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install(monkeypatch)
    told: list[str] = []
    with live_waiter(tmp_path, "1-aaaa", "urgent/1", since=START, rank=URGENT):
        declines(tmp_path, rank=LESS_URGENT, on_wait=told.append)

    assert told and "behind urgent/1" in told[0]
    assert "unnamed holder" not in told[0] and "held by" not in told[0]


def test_a_run_behind_a_waiter_that_names_no_unit_says_another_waiting_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install(monkeypatch)
    told: list[str] = []
    with live_waiter(tmp_path, "1-aaaa", "", since=START, rank=URGENT):
        declines(tmp_path, rank=LESS_URGENT, on_wait=told.append)

    assert told and "behind another waiting run" in told[0]


def test_when_the_slots_are_really_held_the_wait_still_names_the_holders(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install(monkeypatch)
    told: list[str] = []
    holder = ExitStack()
    holder.enter_context(unit_test_slot(tmp_path, 1, holder="a/1"))
    waiter = live_waiter(tmp_path, "1-aaaa", "urgent/1", since=START, rank=URGENT)
    with waiter, pytest.raises(TimeoutError):
        with unit_test_slot(
            tmp_path,
            1,
            holder="new/1",
            rank=LESS_URGENT,
            on_wait=told.append,
            clock=FakeClock(on_sleep=give_up_after_two),
        ):
            pass
    holder.close()

    assert told and "held by a/1" in told[0]


def test_a_failure_while_making_the_marker_leaves_no_staging_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install(monkeypatch)

    def refuse(self: Path, target: Path) -> Path:
        raise OSError("cannot rename")

    with live_waiter(tmp_path, "1-aaaa", "urgent/1", since=START, rank=URGENT):
        monkeypatch.setattr(Path, "rename", refuse)
        with pytest.raises(OSError, match="cannot rename"):
            with unit_test_slot(tmp_path, 1, holder="new/1", rank=LESS_URGENT):
                pass

    assert list(tmp_path.glob("unit-test-registering-*")) == []
