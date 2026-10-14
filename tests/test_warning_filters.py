"""The pytest options make forking a multi-threaded process fail the test that does it
(spec: test-determinism), and leave every other warning as it was."""

import re
import sys
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# What Python 3.12 says when a process that has a second thread forks.
FORK_WARNING = (
    "This process (pid=4242) is multi-threaded, use of fork() may lead to deadlocks in the child."
)
OTHER_WARNING = "an unrelated deprecation"


def configured_filters() -> list[str]:
    options = tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["pytest"]["ini_options"]
    return options.get("filterwarnings", [])


def fork_filter() -> str:
    for entry in configured_filters():
        action, message, category, *_ = [*entry.split(":"), "", ""]
        if (
            action.strip() == "error"
            and category.strip() == "DeprecationWarning"
            and re.match(message, FORK_WARNING)
            and not re.match(message, OTHER_WARNING)
        ):
            return entry
    pytest.fail(
        "[tool.pytest.ini_options] filterwarnings has no entry that turns the "
        f"multi-threaded-fork DeprecationWarning into an error; it holds {configured_filters()!r}"
    )


def test_the_multi_threaded_fork_warning_is_an_error_in_the_pytest_options() -> None:
    assert fork_filter()


FORKS_WHILE_THREADED = """
import os, threading

def test_forks():
    parked = threading.Event()
    keeper = threading.Thread(target=parked.wait, daemon=True)
    keeper.start()
    try:
        pid = os.fork()
        if pid == 0:
            os._exit(0)
        os.waitpid(pid, 0)
    finally:
        parked.set()
        keeper.join()
"""

SPAWNS_WHILE_THREADED = """
import multiprocessing, threading

def test_spawns():
    parked = threading.Event()
    keeper = threading.Thread(target=parked.wait, daemon=True)
    keeper.start()
    try:
        process = multiprocessing.get_context("spawn").Process(target=int)
        process.start()
        process.join(timeout=30)
        assert process.exitcode == 0
    finally:
        parked.set()
        keeper.join()
"""

OTHER_DEPRECATION = f"""
import warnings

def test_warns():
    warnings.warn({OTHER_WARNING!r}, DeprecationWarning)
"""


@pytest.fixture
def filtered(pytester: pytest.Pytester) -> pytest.Pytester:
    entries = "\n    ".join(configured_filters())
    pytester.makeini(f"[pytest]\nfilterwarnings =\n    {entries}\n")
    return pytester


@pytest.mark.skipif(sys.version_info < (3, 12), reason="Python warns about this from 3.12")
def test_a_test_that_forks_while_another_thread_is_alive_fails_with_the_warning(
    filtered: pytest.Pytester,
) -> None:
    fork_filter()
    filtered.makepyfile(test_forking=FORKS_WHILE_THREADED)

    result = filtered.runpytest_subprocess("-p", "no:cacheprovider")

    result.assert_outcomes(failed=1)
    result.stdout.fnmatch_lines(["*multi-threaded, use of fork() may lead to deadlocks*"])


def test_a_test_that_spawns_while_another_thread_is_alive_passes(
    filtered: pytest.Pytester,
) -> None:
    fork_filter()
    filtered.makepyfile(test_spawning=SPAWNS_WHILE_THREADED)

    result = filtered.runpytest_subprocess("-p", "no:cacheprovider")

    result.assert_outcomes(passed=1)


def test_another_deprecation_warning_is_reported_and_does_not_fail(
    filtered: pytest.Pytester,
) -> None:
    fork_filter()
    filtered.makepyfile(test_other=OTHER_DEPRECATION)

    result = filtered.runpytest_subprocess("-p", "no:cacheprovider")

    result.assert_outcomes(passed=1, warnings=1)
