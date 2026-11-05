"""A run that has taken a slot confirms that no live waiter stands before it (spec:
unit-test-concurrency). Between the check and the take a more urgent waiter can register and the
slot be freed; the stand-in `flock` here makes that ordering happen on one thread, every time."""

from __future__ import annotations

import fcntl
import os
from contextlib import ExitStack
from pathlib import Path
from typing import Any

import pytest

from agent_build_kit.pipeline.unit_test_slots import slot_path, unit_test_slot
from tests.fake_clock import START
from tests.unit_test_slot_fakes import FakeClock, live_waiter, waiting_units

URGENT = (0, 2)
LESS_URGENT = (2, 4)


@pytest.mark.parametrize(
    ("holder_holds", "sleeps_before_injection"),
    [(True, 1), (False, 0)],
    ids=["waiting-path", "fast-path"],
)
def test_a_run_that_took_a_slot_gives_it_back_when_a_more_urgent_waiter_registered_meanwhile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    holder_holds: bool,
    sleeps_before_injection: int,
) -> None:
    stack = ExitStack()
    urgent = ExitStack()
    injected_at: list[int] = []
    if holder_holds:
        stack.enter_context(unit_test_slot(tmp_path, 1, holder="holder/1"))

    def after_a_sleep(_count: int) -> None:
        if injected_at:
            urgent.close()  # the urgent waiter goes once the run has had to wait for it

    clock = FakeClock(on_sleep=after_a_sleep)
    real_flock: Any = fcntl.flock
    slot = slot_path(tmp_path, 1)

    def flock(fd: Any, operation: int) -> None:
        takes = (
            operation == fcntl.LOCK_EX | fcntl.LOCK_NB
            and Path(os.fspath(getattr(fd, "name", ""))) == slot
        )
        if takes and not injected_at and len(clock.sleeps) >= sleeps_before_injection:
            injected_at.append(len(clock.sleeps))
            urgent.enter_context(
                live_waiter(tmp_path, "1-aaaa", "urgent/1", since=START, rank=URGENT)
            )
            stack.close()  # the slot is freed
        real_flock(fd, operation)

    monkeypatch.setattr(fcntl, "flock", flock)
    try:
        with unit_test_slot(tmp_path, 1, holder="lazy/1", rank=LESS_URGENT, clock=clock):
            entered_after = len(clock.sleeps)
            recorded = waiting_units(tmp_path)
    finally:
        urgent.close()
        stack.close()

    assert injected_at, "the stand-in never saw the take"
    assert entered_after > injected_at[0]
    assert "urgent/1" not in recorded
