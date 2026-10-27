"""An e2e test runs under its own time limit (spec: e2e-tests-have-their-own-time-limit).

A test with the `local_stack` marker is limited by `--e2e-test-time-limit`, every other
test by `--test-time-limit`. The plugin is driven in a child pytest over the files of
`tests/child_modules/fast_and_e2e_time_limit/`.
"""

from __future__ import annotations

import pytest

from tests import time_limit
from tests.child_pytest import run_scenario

SCENARIO = "fast_and_e2e_time_limit"


def test_a_e2e_test_slower_than_the_fast_limit_passes_in_call_setup_teardown_and_module_fixture(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = run_scenario(
        pytester,
        SCENARIO,
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
        SCENARIO,
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
        SCENARIO,
        "slow_both.py",
        "--test-time-limit=1",
        "--e2e-test-time-limit=20",
        monkeypatch=monkeypatch,
    )

    assert result.code == 1, result.output
    assert "1 failed, 1 passed" in result.output, result.output
    assert "FAILED slow_both.py::test_fast_is_slow" in result.output, result.output
    assert "test exceeded the time limit of 1 seconds" in result.output, result.output
    assert "e2e-test" not in result.output, result.output


def test_the_e2e_limit_has_a_default_and_an_option_and_the_fast_limit_is_as_before(
    pytestconfig: pytest.Config,
) -> None:
    assert time_limit.DEFAULT_E2E_TEST_TIME_LIMIT == 30 * 60
    assert time_limit.e2e_limit(pytestconfig) == time_limit.DEFAULT_E2E_TEST_TIME_LIMIT
    assert time_limit.DEFAULT_TEST_TIME_LIMIT == 60
    assert pytestconfig.getoption("--test-time-limit") == 60


def test_a_e2e_limit_of_zero_turns_it_off_and_leaves_the_fast_limit(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = run_scenario(
        pytester,
        SCENARIO,
        "slow_both.py",
        "--test-time-limit=1",
        "--e2e-test-time-limit=0",
        monkeypatch=monkeypatch,
    )

    assert "1 failed, 1 passed" in result.output, result.output
    assert "FAILED slow_both.py::test_fast_is_slow" in result.output, result.output
    assert "test exceeded the time limit of 1 seconds" in result.output, result.output


def test_the_old_flag_still_limits_an_e2e_test_and_says_it_is_deprecated(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = run_scenario(
        pytester,
        SCENARIO,
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
        SCENARIO,
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
        SCENARIO,
        "marked_e2e.py",
        "--test-time-limit=20",
        "--e2e-test-time-limit=2",
        monkeypatch=monkeypatch,
    )

    assert result.code == 1, result.output
    assert "e2e-test time limit of 2 seconds" in result.output, result.output
