"""A test that forks a multi-threaded process fails (spec: test-determinism).

CPython raises the multi-threaded-fork `DeprecationWarning` after the fork has happened and
drops an exception that a warning filter turns it into, so `filterwarnings = error` cannot
fail the test. This records warnings around each phase of a test and fails the phase when
one is that warning; every other warning reaches pytest's summary as before.
"""

import re
import warnings
from collections.abc import Generator

import pytest

MESSAGE = re.compile(r"This process .* is multi-threaded, use of fork\(\) may lead to deadlocks")


def watched() -> Generator[None]:
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        try:
            yield
        finally:
            recorded = list(caught)
    forks = [w for w in recorded if MESSAGE.search(str(w.message))]
    for other in recorded:
        if other not in forks:
            warnings.warn_explicit(other.message, other.category, other.filename, other.lineno)
    if forks:
        first = forks[0]
        pytest.fail(
            f"{first.filename}:{first.lineno}: {first.message} "
            "(start processes with the `spawn` method)",
            pytrace=False,
        )


@pytest.hookimpl(wrapper=True)
def pytest_runtest_setup(item: pytest.Item) -> Generator[None]:
    yield from watched()


@pytest.hookimpl(wrapper=True)
def pytest_runtest_call(item: pytest.Item) -> Generator[None]:
    yield from watched()


@pytest.hookimpl(wrapper=True)
def pytest_runtest_teardown(item: pytest.Item) -> Generator[None]:
    yield from watched()
