"""A pytest plugin that fails a test which runs past a time limit, from a thread.

The limit, on each of a test's setup, call and teardown, is `--test-time-limit`
seconds (default `DEFAULT_TEST_TIME_LIMIT`), or for a test with the `local_stack`
(tier-2) marker `--tier2-test-time-limit` seconds (default
`DEFAULT_TIER2_TEST_TIME_LIMIT`); zero turns a limit off. A timer thread
signals the main thread when it passes, which interrupts the test wherever it is,
including in a blocking call. The test fails (or errors, in setup or teardown) with
"test exceeded the [tier-2 ]time limit of <n> seconds" and the run goes on.
"""

from __future__ import annotations

import signal
import threading

import pytest

DEFAULT_TEST_TIME_LIMIT = 60
DEFAULT_TIER2_TEST_TIME_LIMIT = 30 * 60


class TimedOut(BaseException):
    """Raised in the main thread when the running test passes its limit."""


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption("--test-time-limit", type=float, default=DEFAULT_TEST_TIME_LIMIT)
    parser.addoption("--tier2-test-time-limit", type=float, default=DEFAULT_TIER2_TEST_TIME_LIMIT)


def _under_limit(item: pytest.Item, phase: str):
    """Run the rest of a hook, setup, call or teardown, under the limit."""
    tier2 = item.get_closest_marker("local_stack") is not None
    limit = item.config.getoption("--tier2-test-time-limit" if tier2 else "--test-time-limit")
    kind = "tier-2 " if tier2 else ""
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
        what = "test" if phase == "call" else f"test {phase}"
        pytest.fail(f"{what} exceeded the {kind}time limit of {limit:g} seconds", pytrace=False)
    finally:
        running = False
        timer.cancel()
        timer.join()
        signal.signal(signal.SIGUSR2, previous)


@pytest.hookimpl(wrapper=True)
def pytest_runtest_setup(item: pytest.Item):
    return (yield from _under_limit(item, "setup"))


@pytest.hookimpl(wrapper=True)
def pytest_runtest_call(item: pytest.Item):
    return (yield from _under_limit(item, "call"))


@pytest.hookimpl(wrapper=True)
def pytest_runtest_teardown(item: pytest.Item):
    return (yield from _under_limit(item, "teardown"))
