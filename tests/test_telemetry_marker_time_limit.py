"""The telemetry marker split test collects the live modules in child runs, so it has the
time limit of the other tests that do: the default is too short for its work on a loaded
machine (spec: telemetry-marker-test-has-room)."""

from __future__ import annotations

import pytest

from tests.live_tag_drift import EVERY_LIVE_MODULE_TIME_LIMIT
from tests.time_limit import DEFAULT_TEST_TIME_LIMIT, limit_for
from tests.tracked_files import ROOT

MODULE = ROOT / "tests" / "test_telemetry_marker.py"
SPLIT_TEST = "test_a_split_on_the_marker_selects_the_otel_items_and_no_other_live_test"


def test_the_split_test_has_the_live_module_time_limit(pytester: pytest.Pytester) -> None:
    items, _ = pytester.inline_genitems(str(MODULE))

    (item,) = [i for i in items if i.name == SPLIT_TEST]

    assert limit_for(item) == EVERY_LIVE_MODULE_TIME_LIMIT
    assert limit_for(item) > DEFAULT_TEST_TIME_LIMIT
