"""A test that lists a child pytest's collection from the repository root gets the loaded limit."""

from __future__ import annotations

import pytest

from tests.child_pytest import collect_listing
from tests.time_limit import LOADED_TEST_TIME_LIMIT, limit_for


def test_a_test_whose_module_takes_collect_listing_gets_the_loaded_limit(
    request: pytest.FixtureRequest,
) -> None:
    assert callable(collect_listing)
    assert limit_for(request.node) == LOADED_TEST_TIME_LIMIT
