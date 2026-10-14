"""A test that forks a multi-threaded process fails, and every other warning is left as it
was (spec: test-determinism). The guard is the plugin `tests.fork_warning_guard`: CPython
drops the exception a `filterwarnings = error` entry would raise for this warning."""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
OTHER_WARNING = "an unrelated deprecation"

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


def run_with_the_guard(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> pytest.RunResult:
    monkeypatch.setenv("PYTHONPATH", str(ROOT))
    return pytester.runpytest_subprocess("-p", "tests.fork_warning_guard", "-p", "no:cacheprovider")


def test_the_repositorys_tests_run_with_the_guard(pytestconfig: pytest.Config) -> None:
    assert pytestconfig.pluginmanager.has_plugin("tests.fork_warning_guard")


def test_a_test_that_forks_while_another_thread_is_alive_fails_with_the_warning(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytester.makepyfile(test_forking=FORKS_WHILE_THREADED)

    result = run_with_the_guard(pytester, monkeypatch)

    result.assert_outcomes(failed=1)
    result.stdout.fnmatch_lines(["*multi-threaded, use of fork() may lead to deadlocks*"])


def test_a_test_that_spawns_while_another_thread_is_alive_passes(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytester.makepyfile(test_spawning=SPAWNS_WHILE_THREADED)

    result = run_with_the_guard(pytester, monkeypatch)

    result.assert_outcomes(passed=1)


def test_another_deprecation_warning_is_reported_and_does_not_fail(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytester.makepyfile(test_other=OTHER_DEPRECATION)

    result = run_with_the_guard(pytester, monkeypatch)

    result.assert_outcomes(passed=1, warnings=1)
