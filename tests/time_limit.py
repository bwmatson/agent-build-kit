"""A pytest plugin that fails a test which runs past a time limit, from a thread.

The limit is `--test-time-limit` seconds (default `DEFAULT_TEST_TIME_LIMIT`). A test
over it fails with "test exceeded the time limit of <n> seconds" and the run goes on.
"""

from __future__ import annotations

import pytest

DEFAULT_TEST_TIME_LIMIT = 60


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption("--test-time-limit", type=float, default=DEFAULT_TEST_TIME_LIMIT)
