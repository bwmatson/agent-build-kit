"""Every test runs under a time limit that fails it from a thread (spec: flaky-tests).

A hung test must fail in a minute, naming the limit, and the run must go on. The plugin
is driven in a child pytest, over a test that busy-waits past a one second limit.

A test marked `time_limit(<seconds>)` is held to that many seconds (spec:
ci-gives-npm-a-longer-timeout), and a `local_stack` test to `--e2e-test-time-limit` (spec:
e2e-tests-have-their-own-time-limit). `limit_for` gives a test's limit from the item alone. The
marked-limit scenarios in `tests/child_modules/marked_time_limit/` swap `threading.Timer` for a
recorder, so no outcome there depends on how long anything takes.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests import time_limit
from tests.child_pytest import run_scenario

ROOT = Path(__file__).parent.parent
E2E_SCENARIO = "fast_and_e2e_time_limit"
MARKED_SCENARIO = "marked_time_limit"

HANGING = """\
import time


def test_hangs():
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        pass


def test_after_it():
    pass
"""


SLOW_TEARDOWN = """\
import time

import pytest


@pytest.fixture
def slow_teardown():
    yield
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        pass


@pytest.fixture
def slow_setup():
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        pass


def test_with_a_slow_teardown(slow_teardown):
    pass


def test_with_a_slow_setup(slow_setup):
    pass


def test_after_them():
    pass
"""


def run_pytest(folder: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "PYTHONPATH": str(ROOT)}
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "tests.time_limit", "-p", "no:cacheprovider", *args],
        cwd=folder,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_a_test_that_hangs_fails_naming_the_limit_and_the_run_goes_on(tmp_path: Path) -> None:
    (tmp_path / "test_hang.py").write_text(HANGING)

    result = run_pytest(tmp_path, "--test-time-limit=1", "-q")

    output = result.stdout + result.stderr
    assert result.returncode == 1, output
    assert "1 failed, 1 passed" in output
    assert "exceeded the CPU time budget of 1 s" in output, output


def test_a_fixture_that_hangs_in_setup_or_teardown_is_an_error_naming_the_limit(
    tmp_path: Path,
) -> None:
    (tmp_path / "test_fixtures.py").write_text(SLOW_TEARDOWN)

    result = run_pytest(tmp_path, "--test-time-limit=1", "-q")

    output = result.stdout + result.stderr
    assert result.returncode == 1, output
    assert "2 passed, 2 errors" in output, output
    assert output.count("exceeded the CPU time budget of 1 s") >= 2, output
    assert "test setup exceeded" in output
    assert "test teardown exceeded" in output


def test_the_default_limit_is_a_minute() -> None:
    assert time_limit.DEFAULT_TEST_TIME_LIMIT == 60


def test_the_suite_runs_under_the_limit(pytestconfig: pytest.Config) -> None:
    assert pytestconfig.pluginmanager.has_plugin("tests.time_limit")
    assert pytestconfig.getoption("--test-time-limit") == time_limit.DEFAULT_TEST_TIME_LIMIT


def test_a_time_limit_marker_gives_its_seconds(request: pytest.FixtureRequest) -> None:
    request.applymarker(pytest.mark.time_limit(5))

    assert time_limit.limit_for(request.node) == 5


def test_a_time_limit_marker_given_as_a_keyword_gives_its_seconds(
    request: pytest.FixtureRequest,
) -> None:
    request.applymarker(pytest.mark.time_limit(seconds=7))

    assert time_limit.limit_for(request.node) == 7


def test_an_unmarked_test_gets_the_fast_limit(request: pytest.FixtureRequest) -> None:
    expected = request.config.getoption("--test-time-limit")

    assert time_limit.limit_for(request.node) == expected


def test_an_e2e_test_keeps_the_e2e_limit_over_its_marker(
    request: pytest.FixtureRequest,
) -> None:
    request.applymarker(pytest.mark.local_stack)
    request.applymarker(pytest.mark.time_limit(1))

    assert time_limit.limit_for(request.node) == time_limit.e2e_limit(request.config)


def test_a_e2e_test_slower_than_the_fast_limit_passes_in_call_setup_teardown_and_module_fixture(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = run_scenario(
        pytester,
        E2E_SCENARIO,
        "slow_e2e.py",
        "--test-time-limit=1",
        "--e2e-test-time-limit=20",
        monkeypatch=monkeypatch,
    )

    assert result.code == 0, result.output
    assert "5 passed" in result.output, result.output
    assert "exceeded" not in result.output


def test_a_e2e_test_past_its_limit_fails_naming_the_e2e_limit(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = run_scenario(
        pytester,
        E2E_SCENARIO,
        "hanging.py",
        "--test-time-limit=2",
        "--e2e-test-time-limit=1",
        monkeypatch=monkeypatch,
    )

    assert result.code == 1, result.output
    assert "e2e-test time limit of 1 seconds" in result.output, result.output


def test_a_test_without_the_marker_still_fails_at_the_fast_limit_with_the_old_message(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = run_scenario(
        pytester,
        E2E_SCENARIO,
        "slow_both.py",
        "--test-time-limit=1",
        "--e2e-test-time-limit=20",
        monkeypatch=monkeypatch,
    )

    assert result.code == 1, result.output
    assert "1 failed, 1 passed" in result.output, result.output
    assert "FAILED slow_both.py::test_fast_is_slow" in result.output, result.output
    assert "test exceeded the CPU time budget of 1 s" in result.output, result.output
    assert "e2e-test" not in result.output, result.output


def test_the_e2e_limit_has_a_default_and_an_option(pytestconfig: pytest.Config) -> None:
    assert time_limit.DEFAULT_E2E_TEST_TIME_LIMIT == 30 * 60
    assert time_limit.e2e_limit(pytestconfig) == time_limit.DEFAULT_E2E_TEST_TIME_LIMIT


def test_a_e2e_limit_of_zero_turns_it_off_and_leaves_the_fast_limit(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = run_scenario(
        pytester,
        E2E_SCENARIO,
        "slow_both.py",
        "--test-time-limit=1",
        "--e2e-test-time-limit=0",
        monkeypatch=monkeypatch,
    )

    assert "1 failed, 1 passed" in result.output, result.output
    assert "FAILED slow_both.py::test_fast_is_slow" in result.output, result.output
    assert "test exceeded the CPU time budget of 1 s" in result.output, result.output


def test_the_old_flag_still_limits_an_e2e_test_and_says_it_is_deprecated(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = run_scenario(
        pytester,
        E2E_SCENARIO,
        "hanging.py",
        "--test-time-limit=2",
        time_limit.OLD_FLAG + "=1",
        monkeypatch=monkeypatch,
    )

    assert result.code == 1, result.output
    assert "e2e-test time limit of 1 seconds" in result.output, result.output
    deprecation = f"{time_limit.OLD_FLAG} is deprecated; use {time_limit.NEW_FLAG}"
    assert deprecation in result.output, result.output


def test_setting_the_old_and_the_new_flag_is_refused_naming_both(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = run_scenario(
        pytester,
        E2E_SCENARIO,
        "hanging.py",
        time_limit.OLD_FLAG + "=1",
        time_limit.NEW_FLAG + "=1",
        monkeypatch=monkeypatch,
    )

    assert result.code != 0, result.output
    assert time_limit.OLD_FLAG in result.output, result.output
    assert time_limit.NEW_FLAG in result.output, result.output


def test_an_e2e_test_with_a_time_limit_marker_keeps_the_e2e_limit(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = run_scenario(
        pytester,
        E2E_SCENARIO,
        "marked_e2e.py",
        "--test-time-limit=20",
        "--e2e-test-time-limit=2",
        monkeypatch=monkeypatch,
    )

    assert result.code == 1, result.output
    assert "e2e-test time limit of 2 seconds" in result.output, result.output


def test_a_marked_test_runs_past_the_default_and_passes(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = run_scenario(
        pytester,
        MARKED_SCENARIO,
        "reads_the_limit.py",
        "--test-time-limit=9000",
        "--e2e-test-time-limit=20",
        "-rA",
        monkeypatch=monkeypatch,
    ).output

    assert "PASSED reads_the_limit.py::test_marked_runs_past_the_default" in output, output
    assert "PASSED reads_the_limit.py::test_marked_runs_past_its_own_limit" in output, output
    assert "PASSED reads_the_limit.py::test_unmarked_beside_them" in output, output
    assert "exceeded" not in output, output


def test_a_marked_test_past_its_own_limit_fails_naming_that_limit(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = run_scenario(
        pytester,
        MARKED_SCENARIO,
        "blocks.py",
        "--test-time-limit=20",
        "--e2e-test-time-limit=20",
        env={"CHILD_FIRE_FIRST_TIMER": "1"},
        monkeypatch=monkeypatch,
    ).output

    assert "FAILED blocks.py::test_marked_runs_past_its_own_limit" in output, output
    assert "test exceeded the wall-clock backstop of 5 s" in output, output


def test_an_unmarked_test_beside_a_marked_one_still_fails_at_the_default(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = run_scenario(
        pytester,
        MARKED_SCENARIO,
        "blocks.py",
        "--test-time-limit=20",
        "--e2e-test-time-limit=20",
        env={"CHILD_FIRE_FIRST_TIMER": "1"},
        monkeypatch=monkeypatch,
    ).output

    assert "FAILED blocks.py::test_unmarked_beside_them" in output, output
    assert "test exceeded the wall-clock backstop of 100 s" in output, output
    assert "2 failed" in output, output
