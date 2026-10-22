"""A test can carry its own time limit (spec: ci-gives-npm-a-longer-timeout).

A test marked `time_limit(<seconds>)` is held to that many seconds in place of
`--test-time-limit`; other tests and the e2e limit are as before. The plugin is driven in
a child pytest over generated files.
"""

from __future__ import annotations

from pathlib import Path

from tests.test_e2e_time_limit import SPIN, run_child

MARKED = (
    SPIN
    + """

@pytest.mark.time_limit(5)
def test_marked_runs_past_the_default():
    spin(2)


@pytest.mark.time_limit(1)
def test_marked_runs_past_its_own_limit():
    spin(3)


def test_unmarked_beside_them():
    spin(2)
"""
)


def test_a_marked_test_runs_past_the_default_and_passes(tmp_path: Path) -> None:
    _, output = run_child(tmp_path, MARKED, "--test-time-limit=1", "--e2e-test-time-limit=20")

    assert "FAILED test_child.py::test_marked_runs_past_the_default" not in output, output
    assert "exceeded the time limit of 5" not in output, output


def test_a_marked_test_past_its_own_limit_fails_naming_that_limit(tmp_path: Path) -> None:
    _, output = run_child(tmp_path, MARKED, "--test-time-limit=20", "--e2e-test-time-limit=20")

    assert "FAILED test_child.py::test_marked_runs_past_its_own_limit" in output, output
    assert "test exceeded the time limit of 1 seconds" in output, output


def test_an_unmarked_test_beside_a_marked_one_still_fails_at_the_default(tmp_path: Path) -> None:
    _, output = run_child(tmp_path, MARKED, "--test-time-limit=1", "--e2e-test-time-limit=20")

    assert "FAILED test_child.py::test_unmarked_beside_them" in output, output
    assert "FAILED test_child.py::test_marked_runs_past_the_default" not in output, output
    assert "1 passed" in output, output
