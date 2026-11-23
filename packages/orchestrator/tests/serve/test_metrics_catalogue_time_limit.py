"""A test that reads the package's metric catalogue gets the loaded time limit: the catalogue's
first read in a worker scans the whole package, and its time depends on the machine's load."""

from __future__ import annotations

import pytest

from agent_build_kit.serve.metrics import catalogue
from tests.time_limit import LOADED_TEST_TIME_LIMIT, limit_for


def test_a_test_that_reads_the_catalogue_gets_the_loaded_limit(
    request: pytest.FixtureRequest,
) -> None:
    assert callable(catalogue)
    assert limit_for(request.node) == LOADED_TEST_TIME_LIMIT
