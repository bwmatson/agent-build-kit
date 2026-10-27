"""The limit a test is held to is decided without running it or waiting on the clock.

A marked test's limit was only observable by spinning past it in a child pytest, which
flaked under load; `limit_for` gives the same answer from the item alone.
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
