"""A pytest plugin that fails a test which runs past a time limit, from a thread.

The limit, on each of a test's setup, call and teardown, is `--test-time-limit`
seconds (default `DEFAULT_TEST_TIME_LIMIT`), or for a test with the `local_stack`
(e2e-test) marker `--e2e-test-time-limit` seconds (default
`DEFAULT_E2E_TEST_TIME_LIMIT`); zero turns a limit off. A timer thread
signals the main thread when it passes, which interrupts the test wherever it is,
including in a blocking call. The test fails (or errors, in setup or teardown) with
"test exceeded the [e2e-test ]time limit of <n> seconds" and the run goes on.
"""

from __future__ import annotations

import signal
import sys
import threading

import pytest

from agent_build_kit.compat_names import old_spelling
from agent_build_kit.model import TestTier

DEFAULT_TEST_TIME_LIMIT = 60
DEFAULT_E2E_TEST_TIME_LIMIT = 30 * 60


class TimedOut(BaseException):
    """Raised in the main thread when the running test passes its limit."""


# The flag under the kind's old spelling, still accepted with a notice.
OLD_FLAG = "--" + old_spelling(TestTier.E2E_TEST) + "-test-time-limit"
NEW_FLAG = "--e2e-test-time-limit"


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption("--test-time-limit", type=float, default=DEFAULT_TEST_TIME_LIMIT)
    parser.addoption(NEW_FLAG, type=float, default=None)
    parser.addoption(OLD_FLAG, type=float, default=None)


def pytest_configure(config: pytest.Config) -> None:
    if config.getoption(OLD_FLAG) is None:
        return
    if config.getoption(NEW_FLAG) is not None:
        raise pytest.UsageError(
            f"{OLD_FLAG} and {NEW_FLAG} are both set; {OLD_FLAG} is the old name"
        )
    print(f"warning: {OLD_FLAG} is deprecated; use {NEW_FLAG}", file=sys.stderr)


def e2e_limit(config: pytest.Config) -> float:
    """The limit of an e2e-test test: the new flag, else the old one, else the default."""
    for flag in (NEW_FLAG, OLD_FLAG):
        if (value := config.getoption(flag)) is not None:
            return value
    return DEFAULT_E2E_TEST_TIME_LIMIT


def _under_limit(item: pytest.Item, phase: str):
    """Run the rest of a hook, setup, call or teardown, under the limit."""
    e2e = item.get_closest_marker("local_stack") is not None
    limit = e2e_limit(item.config) if e2e else item.config.getoption("--test-time-limit")
    kind = "e2e-test " if e2e else ""
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
