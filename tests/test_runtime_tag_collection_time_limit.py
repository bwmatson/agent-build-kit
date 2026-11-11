"""A test that takes `assert_runs_on_claude_code_alone` gets the loaded limit."""

from __future__ import annotations

import pytest

from tests.runtime_tag_collection import assert_runs_on_claude_code_alone
from tests.time_limit import LOADED_TEST_TIME_LIMIT, limit_for


def test_a_test_whose_module_takes_the_claude_code_collection_gets_the_loaded_limit(
    request: pytest.FixtureRequest,
) -> None:
    assert callable(assert_runs_on_claude_code_alone)
    assert limit_for(request.node) == LOADED_TEST_TIME_LIMIT
