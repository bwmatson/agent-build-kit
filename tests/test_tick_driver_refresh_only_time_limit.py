"""A test that uses only the tick driver's refresh counter keeps the default time limit."""

from __future__ import annotations

import pytest

from tests.tick_driver import count_refreshes
from tests.time_limit import DEFAULT_TEST_TIME_LIMIT, limit_for


def test_a_test_that_only_counts_refreshes_keeps_the_default_limit(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    count_refreshes(monkeypatch)

    assert limit_for(request.node) == DEFAULT_TEST_TIME_LIMIT
