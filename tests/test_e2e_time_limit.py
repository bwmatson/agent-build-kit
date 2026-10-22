"""An e2e test runs under its own time limit (spec: e2e-tests-have-their-own-time-limit).

A test with the `local_stack` marker is limited by `--e2e-test-time-limit`, every other
test by `--test-time-limit`. The plugin is driven in a child pytest over generated files.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests import time_limit

ROOT = Path(__file__).parent.parent

INI = """\
[pytest]
markers =
    local_stack: an e2e test
"""

SPIN = """\
import time

import pytest


def spin(seconds):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        pass
"""

SLOW_E2E = (
    SPIN
    + """

@pytest.fixture(scope="module")
def module_tick():
    spin(3)


@pytest.fixture
def slow_setup():
    spin(3)


@pytest.fixture
def slow_teardown():
    yield
    spin(3)


@pytest.mark.local_stack
def test_call_is_slow():
    spin(3)


@pytest.mark.local_stack
def test_setup_is_slow(slow_setup):
    pass


@pytest.mark.local_stack
def test_teardown_is_slow(slow_teardown):
    pass


@pytest.mark.local_stack
def test_first_with_module_fixture(module_tick):
    pass


@pytest.mark.local_stack
def test_second_with_module_fixture(module_tick):
    pass
"""
)

HANGING = (
    SPIN
    + """

@pytest.mark.local_stack
def test_e2e_hangs():
    spin(20)


def test_fast_hangs():
    spin(20)
"""
)

SLOW_BOTH = (
    SPIN
    + """

@pytest.mark.local_stack
def test_e2e_is_slow():
    spin(3)


def test_fast_is_slow():
    spin(3)
"""
)


MARKED_E2E = (
    SPIN
    + """

@pytest.mark.local_stack
@pytest.mark.time_limit(1)
def test_e2e_keeps_the_e2e_limit():
    spin(3)
"""
)


def run_child(folder: Path, source: str, *args: str) -> tuple[int, str]:
    (folder / "pytest.ini").write_text(INI)
    (folder / "test_child.py").write_text(source)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "tests.time_limit",
            "-p",
            "no:cacheprovider",
            "-q",
            *args,
        ],
        cwd=folder,
        env={**os.environ, "PYTHONPATH": str(ROOT)},
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode, result.stdout + result.stderr


def test_a_e2e_test_slower_than_the_fast_limit_passes_in_call_setup_teardown_and_module_fixture(
    tmp_path: Path,
) -> None:
    code, output = run_child(tmp_path, SLOW_E2E, "--test-time-limit=1", "--e2e-test-time-limit=20")

    assert code == 0, output
    assert "5 passed" in output, output
    assert "exceeded" not in output


def test_a_e2e_test_past_its_limit_fails_naming_the_e2e_limit(tmp_path: Path) -> None:
    code, output = run_child(tmp_path, HANGING, "--test-time-limit=2", "--e2e-test-time-limit=1")

    assert code == 1, output
    assert "e2e-test time limit of 1 seconds" in output, output


def test_a_test_without_the_marker_still_fails_at_the_fast_limit_with_the_old_message(
    tmp_path: Path,
) -> None:
    code, output = run_child(tmp_path, SLOW_BOTH, "--test-time-limit=1", "--e2e-test-time-limit=20")

    assert code == 1, output
    assert "1 failed, 1 passed" in output, output
    assert "FAILED test_child.py::test_fast_is_slow" in output, output
    assert "test exceeded the time limit of 1 seconds" in output, output
    assert "e2e-test" not in output, output


def test_the_e2e_limit_has_a_default_and_an_option_and_the_fast_limit_is_as_before(
    pytestconfig: pytest.Config,
) -> None:
    assert time_limit.DEFAULT_E2E_TEST_TIME_LIMIT == 30 * 60
    assert time_limit.e2e_limit(pytestconfig) == time_limit.DEFAULT_E2E_TEST_TIME_LIMIT
    assert time_limit.DEFAULT_TEST_TIME_LIMIT == 60
    assert pytestconfig.getoption("--test-time-limit") == 60


def test_a_e2e_limit_of_zero_turns_it_off_and_leaves_the_fast_limit(tmp_path: Path) -> None:
    code, output = run_child(tmp_path, SLOW_BOTH, "--test-time-limit=1", "--e2e-test-time-limit=0")

    assert "1 failed, 1 passed" in output, output
    assert "FAILED test_child.py::test_fast_is_slow" in output, output
    assert "test exceeded the time limit of 1 seconds" in output, output


def test_the_old_flag_still_limits_an_e2e_test_and_says_it_is_deprecated(
    tmp_path: Path,
) -> None:
    code, output = run_child(tmp_path, HANGING, "--test-time-limit=2", time_limit.OLD_FLAG + "=1")

    assert code == 1, output
    assert "e2e-test time limit of 1 seconds" in output, output
    assert f"{time_limit.OLD_FLAG} is deprecated; use {time_limit.NEW_FLAG}" in output, output


def test_setting_the_old_and_the_new_flag_is_refused_naming_both(tmp_path: Path) -> None:
    code, output = run_child(
        tmp_path, HANGING, time_limit.OLD_FLAG + "=1", time_limit.NEW_FLAG + "=1"
    )

    assert code != 0, output
    assert time_limit.OLD_FLAG in output and time_limit.NEW_FLAG in output, output


def test_an_e2e_test_with_a_time_limit_marker_keeps_the_e2e_limit(tmp_path: Path) -> None:
    code, output = run_child(
        tmp_path, MARKED_E2E, "--test-time-limit=20", "--e2e-test-time-limit=2"
    )

    assert code == 1, output
    assert "e2e-test time limit of 2 seconds" in output, output
