"""The limit a test is held to is decided without running it or waiting on the clock.

`limit_for` gives a test's limit from the item alone. The child-pytest tests in
`test_marked_time_limit.py` no longer spin on the wall clock: they read the limit the hook
arms from a recording timer, so they cannot flake under load.
"""

from __future__ import annotations

import pytest

from tests import time_limit


def test_a_time_limit_marker_gives_its_seconds(request: pytest.FixtureRequest) -> None:
    request.applymarker(pytest.mark.time_limit(5))

    assert time_limit.limit_for(request.node) == 5


def test_a_time_limit_marker_given_as_a_keyword_gives_its_seconds(
    request: pytest.FixtureRequest,
) -> None:
    request.applymarker(pytest.mark.time_limit(seconds=7))

    assert time_limit.limit_for(request.node) == 7


def test_an_unmarked_test_gets_the_fast_limit(request: pytest.FixtureRequest) -> None:
    expected = request.config.getoption("--test-time-limit")

    assert time_limit.limit_for(request.node) == expected


def test_an_e2e_test_keeps_the_e2e_limit_over_its_marker(
    request: pytest.FixtureRequest,
) -> None:
    request.applymarker(pytest.mark.local_stack)
    request.applymarker(pytest.mark.time_limit(1))

    assert time_limit.limit_for(request.node) == time_limit.e2e_limit(request.config)
