"""The tests that collect the live modules, or drive the unit graph many times, are load-proof.

Each collects every live module of the kit in-process, or compiles the unit graph for every step
of a pass, which under parallel load takes longer than the default per-test time limit, so the
limit would interrupt it at random. They are judged here on the limit they run under, not on how
long a host took.
"""

from __future__ import annotations

import pytest

from tests.live_tag_drift import EVERY_LIVE_MODULE_TIME_LIMIT
from tests.runtime_tag_collection import ROOT
from tests.time_limit import DEFAULT_TEST_TIME_LIMIT, limit_for

COLLECTING_TESTS = [
    (
        "test_claude_without_acp_gap_list.py",
        "test_the_kits_current_list_matches_the_documents_without_a_warning",
    ),
    (
        "test_live_tests_are_tagged.py",
        "test_every_test_of_the_kits_live_modules_that_starts_an_agent_has_exactly_one_tag",
    ),
    (
        "test_live_split_names.py",
        "test_every_tagged_live_test_of_the_kit_is_in_one_derived_split",
    ),
    (
        "cli/test_lane_hand_back_readmit.py",
        "test_a_pass_starts_a_handed_back_unit_in_a_build_worker_and_the_lane_does_not_list_it",
    ),
    (
        "cli/test_lane_hand_back_readmit.py",
        "test_a_unit_handed_back_with_no_feedback_is_not_the_lanes_and_a_build_worker_takes_it",
    ),
    (
        "test_live_tests_across_dimensions.py",
        "test_no_two_live_tests_of_the_kit_differ_in_name_only_by_a_dimension_value",
    ),
    (
        "test_telemetry_marker.py",
        "test_a_split_on_the_marker_selects_the_otel_items_and_no_other_live_test",
    ),
]


@pytest.mark.parametrize(("module", "name"), COLLECTING_TESTS)
def test_a_test_that_collects_every_live_module_has_a_limit_beyond_a_loaded_collection(
    pytester: pytest.Pytester, module: str, name: str
) -> None:
    items, _ = pytester.inline_genitems(str(ROOT / "tests" / module))
    item = next(i for i in items if i.name == name)

    assert limit_for(item) >= EVERY_LIVE_MODULE_TIME_LIMIT > DEFAULT_TEST_TIME_LIMIT
