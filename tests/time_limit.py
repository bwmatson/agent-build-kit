"""A pytest plugin that fails a test which runs past a time limit, from a thread.

The limit is `--test-time-limit` seconds (default `DEFAULT_TEST_TIME_LIMIT`). A timer
thread signals the main thread when it passes, which interrupts the test wherever it is,
including in a blocking call. The test fails with "test exceeded the time limit of <n>
seconds" and the run goes on.
"""

from __future__ import annotations

import signal
import threading

import pytest

DEFAULT_TEST_TIME_LIMIT = 60


class TimedOut(BaseException):
    """Raised in the main thread when the running test passes its limit."""


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption("--test-time-limit", type=float, default=DEFAULT_TEST_TIME_LIMIT)


@pytest.hookimpl(wrapper=True)
def pytest_runtest_call(item: pytest.Item):
    limit = item.config.getoption("--test-time-limit")
    if limit <= 0 or threading.current_thread() is not threading.main_thread():
        return (yield)
    running = True

    def interrupt(signum, frame) -> None:
        if running:
            raise TimedOut

    previous = signal.signal(signal.SIGUSR2, interrupt)
    main = threading.get_ident()
    timer = threading.Timer(limit, signal.pthread_kill, (main, signal.SIGUSR2))
    timer.daemon = True
    timer.start()
    try:
        return (yield)
    except TimedOut:
        pytest.fail(f"test exceeded the time limit of {limit:g} seconds", pytrace=False)
    finally:
        running = False
        timer.cancel()
        signal.signal(signal.SIGUSR2, previous)
