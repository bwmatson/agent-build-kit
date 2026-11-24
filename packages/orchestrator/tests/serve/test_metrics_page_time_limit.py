"""A test that reads the metrics page, which reads the package's catalogue, gets the loaded time
limit; this module imports `metrics_page` alone, so the rule is pinned for that reader too."""

from __future__ import annotations

import pytest

from agent_build_kit.serve.metrics import metrics_page
from tests.time_limit import LOADED_TEST_TIME_LIMIT, limit_for


def test_a_test_that_reads_the_metrics_page_gets_the_loaded_limit(
    request: pytest.FixtureRequest,
) -> None:
    assert callable(metrics_page)
    assert limit_for(request.node) == LOADED_TEST_TIME_LIMIT
