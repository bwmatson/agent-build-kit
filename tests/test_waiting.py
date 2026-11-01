"""The shared wait-for-condition helper (spec: flaky-tests)."""

from __future__ import annotations

import threading

import pytest

from tests import chat_serving
from tests.waiting import wait_for


def test_it_returns_once_the_condition_holds() -> None:
    done = threading.Event()
    worker = threading.Thread(target=done.set)
    worker.start()

    wait_for(done.is_set, what="the thread to run", timeout=30)

    worker.join()
    assert done.is_set()


def test_it_returns_at_once_for_a_condition_already_true() -> None:
    wait_for(lambda: True, what="nothing", timeout=30)


def test_it_names_what_it_waited_for_when_the_condition_never_holds() -> None:
    with pytest.raises(TimeoutError, match="the moon to fall"):
        wait_for(lambda: False, what="the moon to fall", timeout=0.1)


def test_the_bound_on_a_served_turn_outlasts_a_loaded_machine_starting_an_agent() -> None:
    # The bound only ends a wait that never comes true, so a long one costs a passing test nothing.
    # 15 seconds was passed by 3 of 44 copies of one test started at once on a 22-core machine.
    assert chat_serving.WAIT >= 60, "a turn's first event waits on a real process starting"
