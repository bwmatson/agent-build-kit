"""A test that takes `built` or `built_after_a_pair` gets the loaded limit."""

from __future__ import annotations

import pytest

from tests.graph.branch_fakes import built, built_after_a_pair
from tests.time_limit import LOADED_TEST_TIME_LIMIT, limit_for


@pytest.mark.parametrize("helper", [built, built_after_a_pair], ids=lambda h: h.__name__)
def test_a_test_whose_module_takes_a_branch_build_helper_gets_the_loaded_limit(
    helper: object, request: pytest.FixtureRequest
) -> None:
    assert callable(helper)
    assert limit_for(request.node) == LOADED_TEST_TIME_LIMIT
