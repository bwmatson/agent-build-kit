"""A test that reaches the tick driver only through `make_lane` gets the loaded time limit."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from tests.lane_run_usage_support import Lane, make_lane  # noqa: F401 — fixture
from tests.time_limit import LOADED_TEST_TIME_LIMIT, limit_for


def test_a_test_that_takes_make_lane_gets_the_loaded_limit(
    request: pytest.FixtureRequest,
    make_lane: Callable[..., Lane],  # noqa: F811 — fixture
) -> None:
    assert limit_for(request.node) == LOADED_TEST_TIME_LIMIT
