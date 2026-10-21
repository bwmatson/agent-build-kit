"""The kit's live tests are written once across the dimensions' values: the setup and usage-guard
tests and the build test run over every runtime, the telemetry tests over every runtime and
telemetry value, each parameter carrying the one marker of its value (spec: e2e-dimensions)."""

from __future__ import annotations

from collections import defaultdict

import pytest

from tests.live_tag_drift import DIMENSIONS, value_name_drift
from tests.runtime_tag_collection import ROOT

INTEGRATION = ROOT / "tests" / "integration"
SETUP = "test_runtime_scratch_setup.py"
USAGE_GUARD = "test_runtime_scratch_usage_guard.py"
BUILD_UNIT = "test_build_unit.py"
TELEMETRY = "test_telemetry_stack.py"
INIT = "test_init_runtime_live_stack.py"

OLD_NAMES = {
    "test_acp_gets_a_runtimes_entry_and_the_override_from_the_agent_command_setting",
    "test_claude_code_gets_no_entry_and_pins_the_runtime_and_sets_its_account_variables",
    "test_claude_code_has_the_guard_off_unless_it_opts_in_and_acp_is_unchanged",
    "test_a_ticks_trace_is_found_in_the_trace_store_by_the_unit_id",
    "test_a_ticks_duration_series_are_in_the_metrics_store_without_a_unit_id",
    "test_a_tick_with_the_endpoint_pointing_at_nothing_finishes_and_writes_nothing",
}


def items_of(pytester: pytest.Pytester, *files: str) -> list[pytest.Item]:
    items, _ = pytester.inline_genitems(*(str(INTEGRATION / f) for f in files))
    return items


def values_of(item: pytest.Item, dimension: str) -> set[str]:
    markers = {m.name for m in item.iter_markers()}
    return {v for v, spec in DIMENSIONS[dimension].items() if spec.marker in markers}


def name_of(item: pytest.Item) -> str:
    return getattr(item, "originalname", item.name)


def values_by_test(items: list[pytest.Item], dimension: str) -> dict[str, set[str]]:
    found: dict[str, set[str]] = defaultdict(set)
    for item in items:
        found[name_of(item)] |= values_of(item, dimension)
    return found


def assert_one_value_each(items: list[pytest.Item], *dimensions: str) -> None:
    assert items
    for item in items:
        for dimension in dimensions:
            carried = values_of(item, dimension)
            assert len(carried) == 1, f"{item.nodeid}: carries {sorted(carried)} of {dimension}"
            assert carried <= set(item.nodeid.split("[")[-1].rstrip("]").split("-")), item.nodeid


@pytest.mark.parametrize("file", [SETUP, USAGE_GUARD])
def test_the_scratch_tests_run_over_every_runtime_with_value_neutral_names(
    pytester: pytest.Pytester, file: str
) -> None:
    items = items_of(pytester, file)

    assert_one_value_each(items, "runtime")
    for name, runtimes in values_by_test(items, "runtime").items():
        assert runtimes == set(DIMENSIONS["runtime"]), name
    assert value_name_drift(items, DIMENSIONS) == []


def test_the_old_per_value_test_names_are_gone(pytester: pytest.Pytester) -> None:
    items = items_of(pytester, SETUP, USAGE_GUARD, TELEMETRY)

    assert OLD_NAMES.isdisjoint({name_of(i) for i in items})


def test_the_build_unit_test_runs_over_every_runtime(pytester: pytest.Pytester) -> None:
    items = items_of(pytester, BUILD_UNIT)

    assert_one_value_each(items, "runtime")
    for name, runtimes in values_by_test(items, "runtime").items():
        assert runtimes == set(DIMENSIONS["runtime"]), name


def test_the_telemetry_tests_run_over_the_runtime_and_telemetry_values(
    pytester: pytest.Pytester,
) -> None:
    items = items_of(pytester, TELEMETRY)

    assert_one_value_each(items, "runtime", "telemetry")
    assert not any("stack" in name_of(i) for i in items)
    assert any("sink" in name_of(i) for i in items)
    for name, telemetry in values_by_test(items, "telemetry").items():
        assert telemetry == set(DIMENSIONS["telemetry"]), name
    assert value_name_drift(items, DIMENSIONS) == []


def test_the_init_runtime_live_tests_carry_the_acp_tag(pytester: pytest.Pytester) -> None:
    items = items_of(pytester, INIT)

    assert items
    for item in items:
        assert values_of(item, "runtime") == {"acp"}, item.nodeid
