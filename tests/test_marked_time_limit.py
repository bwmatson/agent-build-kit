"""A test can carry its own time limit (spec: ci-gives-npm-a-longer-timeout).

A test marked `time_limit(<seconds>)` is held to that many seconds in place of
`--test-time-limit`; other tests and the e2e limit are as before. The plugin is driven in
a child pytest over generated files. No outcome here depends on how long anything takes:
the child swaps `threading.Timer` for a recorder, so a test reads the limit the hook armed,
and where a test must run past its limit the recorder fires the first timer of that test
at once and the test blocks until the signal arrives.
"""

from __future__ import annotations

from pathlib import Path

from tests.test_e2e_time_limit import run_child

RECORDER = """\
import threading

import pytest

armed = []
FIRE = {fire}


@pytest.fixture(autouse=True)
def recording_timer(monkeypatch):
    armed.clear()
    real = threading.Timer

    class Recording(real):
        def __init__(self, interval, *args, **kwargs):
            first = not armed
            armed.append(interval)
            super().__init__(0 if FIRE and first else interval, *args, **kwargs)

    monkeypatch.setattr(threading, "Timer", Recording)
"""

READS_THE_LIMIT = (
    RECORDER.format(fire=False)
    + """

@pytest.mark.time_limit(5000)
def test_marked_runs_past_the_default():
    assert armed[-1] == 5000


@pytest.mark.time_limit(7000)
def test_marked_runs_past_its_own_limit():
    assert armed[-1] == 7000


def test_unmarked_beside_them():
    assert armed[-1] == 9000
"""
)

BLOCKS = (
    RECORDER.format(fire=True)
    + """

@pytest.mark.time_limit(1)
def test_marked_runs_past_its_own_limit():
    threading.Event().wait()


def test_unmarked_beside_them():
    threading.Event().wait()
"""
)


def test_a_marked_test_runs_past_the_default_and_passes(tmp_path: Path) -> None:
    _, output = run_child(
        tmp_path, READS_THE_LIMIT, "--test-time-limit=9000", "--e2e-test-time-limit=20", "-rA"
    )

    assert "PASSED test_child.py::test_marked_runs_past_the_default" in output, output
    assert "PASSED test_child.py::test_marked_runs_past_its_own_limit" in output, output
    assert "PASSED test_child.py::test_unmarked_beside_them" in output, output
    assert "exceeded" not in output, output


def test_a_marked_test_past_its_own_limit_fails_naming_that_limit(tmp_path: Path) -> None:
    _, output = run_child(tmp_path, BLOCKS, "--test-time-limit=20", "--e2e-test-time-limit=20")

    assert "FAILED test_child.py::test_marked_runs_past_its_own_limit" in output, output
    assert "test exceeded the time limit of 1 seconds" in output, output


def test_an_unmarked_test_beside_a_marked_one_still_fails_at_the_default(tmp_path: Path) -> None:
    _, output = run_child(tmp_path, BLOCKS, "--test-time-limit=20", "--e2e-test-time-limit=20")

    assert "FAILED test_child.py::test_unmarked_beside_them" in output, output
    assert "test exceeded the time limit of 20 seconds" in output, output
    assert "2 failed" in output, output
