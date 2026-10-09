"""Every test runs under a time limit that fails it from a thread (spec: flaky-tests).

A hung test must fail in a minute, naming the limit, and the run must go on. The plugin
is driven in a child pytest, over a test that busy-waits past a one second limit.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from tests import time_limit

ROOT = Path(__file__).parent.parent

HANGING = """\
import time


def test_hangs():
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        pass


def test_after_it():
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
    assert re.search(r"time limit of 1 seconds?", output), output


def test_the_default_limit_is_a_minute() -> None:
    assert time_limit.DEFAULT_TEST_TIME_LIMIT == 60


def test_the_suite_runs_under_the_limit(pytestconfig: pytest.Config) -> None:
    assert pytestconfig.pluginmanager.has_plugin("tests.time_limit")
    assert pytestconfig.getoption("--test-time-limit") == time_limit.DEFAULT_TEST_TIME_LIMIT
