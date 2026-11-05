"""A test built on the `ticks` fixture runs whole faked passes, so it gets the loaded time limit."""

from __future__ import annotations

import pytest

from tests.cli.test_tick_telemetry import (
    ticks,  # noqa: F401 — the hook looks for the fixture among the module's names
)
from tests.time_limit import LOADED_TEST_TIME_LIMIT, limit_for


def test_a_test_whose_module_takes_the_ticks_fixture_gets_the_loaded_limit(
    request: pytest.FixtureRequest,
) -> None:
    assert limit_for(request.node) == LOADED_TEST_TIME_LIMIT
