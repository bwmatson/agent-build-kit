"""A kill takes a moment to take effect: `still_alive` gives it that moment by asking again,
through an injected sleep, instead of judging the instant after the signal."""

from __future__ import annotations

import os
import subprocess
import sys

from tests.runtimes.policy_fake_agents import still_alive


def test_a_process_that_dies_while_it_is_waited_for_is_not_still_alive() -> None:
    child = subprocess.Popen(
        [sys.executable, "-c", "import threading; threading.Event().wait()"],
        stdin=subprocess.DEVNULL,
    )
    slept: list[float] = []

    def die_on_first_sleep(seconds: float) -> None:
        slept.append(seconds)
        child.kill()
        child.wait()

    assert still_alive([child.pid], sleep=die_on_first_sleep) == []
    assert len(slept) == 1


def test_a_process_that_stays_is_reported_after_a_bounded_number_of_asks() -> None:
    slept: list[float] = []

    assert still_alive([os.getpid()], sleep=slept.append, attempts=5) == [os.getpid()]
    assert len(slept) == 4
