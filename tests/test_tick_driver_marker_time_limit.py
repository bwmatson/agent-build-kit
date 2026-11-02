"""A time limit set on a whole module wins over the loaded limit the tick driver brings."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.tick_driver import make_setup
from tests.time_limit import DEFAULT_TEST_TIME_LIMIT, limit_for

pytestmark = pytest.mark.time_limit(DEFAULT_TEST_TIME_LIMIT * 2)


def test_a_module_s_own_time_limit_wins_over_the_drivers(
    request: pytest.FixtureRequest, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    make_setup(tmp_path, monkeypatch)

    assert limit_for(request.node) == DEFAULT_TEST_TIME_LIMIT * 2
