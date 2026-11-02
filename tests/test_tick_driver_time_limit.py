"""A test built on the tick driver runs whole faked ticks, so it gets the loaded time limit."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.tick_driver import make_setup
from tests.time_limit import LOADED_TEST_TIME_LIMIT, limit_for


def test_a_test_that_builds_the_driver_s_setup_gets_the_loaded_limit(
    request: pytest.FixtureRequest, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    make_setup(tmp_path, monkeypatch)

    assert limit_for(request.node) == LOADED_TEST_TIME_LIMIT
