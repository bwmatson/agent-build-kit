"""A test that takes the graph's `build` gets the loaded limit."""

from __future__ import annotations

import pytest

from packages.worker.tests.graph.test_build_path import build
from tests.time_limit import LOADED_TEST_TIME_LIMIT, limit_for


def test_a_test_whose_module_takes_the_graph_build_gets_the_loaded_limit(
    request: pytest.FixtureRequest,
) -> None:
    assert callable(build)
    assert limit_for(request.node) == LOADED_TEST_TIME_LIMIT
