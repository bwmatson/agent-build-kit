"""A test that takes `piece_built` gets the loaded limit."""

from __future__ import annotations

import pytest

from tests.graph.piece_fakes import piece_built
from tests.time_limit import LOADED_TEST_TIME_LIMIT, limit_for


def test_a_test_whose_module_takes_the_piece_build_gets_the_loaded_limit(
    request: pytest.FixtureRequest,
) -> None:
    assert callable(piece_built)
    assert limit_for(request.node) == LOADED_TEST_TIME_LIMIT
