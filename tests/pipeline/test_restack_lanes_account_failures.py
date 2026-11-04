"""When a lane cannot start a worker, or one lane's restart fails, the account's other waiting
restacks are still started and the lanes' waiters are still told (spec: account-project-limits).

A worker is made to fail by a `Thread.start` that raises once, armed by the test, so nothing
depends on the clock.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

from agent_build_kit.pipeline.restack_lane import RestackLanes
from agent_build_kit.pipeline.units import ProjectKey
from tests.pipeline.test_restack_lanes_account import Caps, account_of, lanes_of
from tests.restack_lane_fakes import WAIT, Restacks
from tests.restack_lanes_fakes import API, WEB, Made, unit_of

JOBS = ProjectKey(repo="app", project="jobs")


@pytest.fixture
def restacks() -> Restacks:
    return Restacks()


@pytest.fixture
def made(tmp_path: Path, restacks: Restacks) -> Made:
    return Made(tmp_path / "locks", restacks)


@pytest.fixture
def one_at_a_time(made: Made, restacks: Restacks) -> Iterator[RestackLanes]:
    """Lanes of cap two each, the account `kit` allowing one restack at once."""
    yield from lanes_of(made, restacks, Caps(kit=1), account_of)


class FailingStart:
    """A `Thread.start` that raises once for a lane's worker when armed."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.armed = False
        self.raised = 0
        real = threading.Thread.start

        def start(thread: threading.Thread) -> None:
            if self.armed and thread.name == "restack":
                self.armed = False
                self.raised += 1
                raise RuntimeError("can't start new thread")
            real(thread)

        monkeypatch.setattr(threading.Thread, "start", start)


def test_a_worker_that_cannot_start_leaves_the_waiting_entries_of_the_other_lanes_to_start(
    one_at_a_time: RestackLanes,
    made: Made,
    restacks: Restacks,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failing = FailingStart(monkeypatch)
    for number, key in [(1, WEB), (3, WEB), (4, WEB), (2, API)]:
        one_at_a_time.hand_over(unit_of(number, key))
    assert restacks.begun["feature/1"].wait(WAIT)
    ends = one_at_a_time.finished()
    failing.armed = True

    # The end of 1 starts 3 in its own lane first, which fails to get a worker.
    restacks.release("feature/1")

    assert restacks.begun["feature/2"].wait(WAIT)
    ends.result(timeout=WAIT)
    assert failing.raised == 1
    assert made.by_project[WEB].waiting == ["feature/3", "feature/4"]
    assert one_at_a_time.running == ["feature/2"]


def test_the_entry_that_found_no_worker_keeps_its_place_and_its_account_place_is_returned(
    one_at_a_time: RestackLanes,
    made: Made,
    restacks: Restacks,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failing = FailingStart(monkeypatch)
    for number, key in [(1, WEB), (3, WEB), (4, WEB), (2, API)]:
        one_at_a_time.hand_over(unit_of(number, key))
    assert restacks.begun["feature/1"].wait(WAIT)
    failing.armed = True
    restacks.release("feature/1")
    assert restacks.begun["feature/2"].wait(WAIT)

    # Had 3's place with the account leaked, the account would stay full and 3 never start.
    restacks.release("feature/2")

    assert restacks.begun["feature/3"].wait(WAIT)
    assert made.by_project[WEB].waiting == ["feature/4"]
    assert one_at_a_time.running == ["feature/3"]


def test_a_start_that_fails_on_a_hand_over_restores_the_queue_and_the_place(
    one_at_a_time: RestackLanes,
    made: Made,
    restacks: Restacks,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failing = FailingStart(monkeypatch)
    failing.armed = True

    with pytest.raises(RuntimeError, match="can't start"):
        one_at_a_time.hand_over(unit_of(1, WEB))

    assert one_at_a_time.running == []
    assert made.by_project[WEB].waiting == ["feature/1"]
    assert not one_at_a_time.account_full(unit_of(1, WEB))
    one_at_a_time.hand_over(unit_of(2, API))
    assert restacks.begun["feature/2"].wait(WAIT)


def test_a_lane_whose_restart_fails_does_not_stop_the_restart_of_the_lanes_after_it(
    one_at_a_time: RestackLanes,
    made: Made,
    restacks: Restacks,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for number, key in [(1, WEB), (2, API), (3, JOBS)]:
        one_at_a_time.hand_over(unit_of(number, key))
    assert restacks.begun["feature/1"].wait(WAIT)

    def broken() -> None:
        raise RuntimeError("restart failed")

    monkeypatch.setattr(made.by_project[API], "restart", broken)
    ends = one_at_a_time.finished()

    restacks.release("feature/1")

    # The lanes are restarted in the order they were made: API's fails, JOBS's is still met.
    assert restacks.begun["feature/3"].wait(WAIT)
    ends.result(timeout=WAIT)
    assert one_at_a_time.running == ["feature/3"]
