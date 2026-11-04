"""A test built on the tick pass runs a whole faked pass, so it gets the loaded time limit."""

from __future__ import annotations

import pytest

from tests.tick_pass import tick
from tests.time_limit import LOADED_TEST_TIME_LIMIT, limit_for


def test_a_test_whose_module_takes_the_tick_pass_gets_the_loaded_limit(
    request: pytest.FixtureRequest,
) -> None:
    assert callable(tick)
    assert limit_for(request.node) == LOADED_TEST_TIME_LIMIT
