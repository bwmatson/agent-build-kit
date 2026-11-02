"""A test that scans the whole repository is an integration test, so the default unit run skips it.

Such a scan reads every test file; alone it takes seconds and under parallel load it is the test
that runs past its time limit (`test_live_tag_drift`'s scan took 10 to 24 seconds, loaded).
Add a scan here when it is found; CI's `integration` check still runs it before a merge.

Each named scan carries the selector on the test itself, the baseline holds none of them, and the
default run collects none of them while it still collects the logic tests of a check. A scan not
named here is found by its syntax (`tests/wide_scans.py`, cases in `tests/test_wide_scans.py`) and
fails the guard below unless the baseline names it; the baseline may only shrink.
"""

from __future__ import annotations

import pytest

from tests.tracked_files import ROOT
from tests.wide_scans import TESTS_ROOT, check_tests, load_baseline

WIDE_SCANS = [
    (
        "test_live_tag_drift.py",
        "test_every_module_the_old_glob_and_text_match_found_is_still_found",
    ),
    ("docs/test_state_home_documented.py", "test_no_document_says_the_store_is_committed"),
    (
        "test_agent_call_guard.py",
        "test_every_agent_call_in_the_source_records_or_is_on_the_allowlist",
    ),
    (
        "test_agent_call_rows.py",
        "test_the_guard_passes_over_the_real_source_with_an_empty_allowlist",
    ),
    (
        "test_agent_start_signals.py",
        "test_every_helper_module_that_starts_an_agent_is_in_the_table_or_excused_with_a_reason",
    ),
    (
        "test_atomic_write_guard.py",
        "test_no_module_but_the_shared_one_replaces_a_file_from_a_temporary",
    ),
    (
        "test_child_pytest_sources_are_real_files.py",
        "test_the_repository_has_no_unlisted_or_stale_module",
    ),
    (
        "test_claude_without_acp_gap_list.py",
        "test_the_kits_current_list_matches_the_documents_without_a_warning",
    ),
    (
        "test_docs_e2e_splits.py",
        "test_no_document_names_the_old_runtime_lists_once_the_splits_are_documented",
    ),
    (
        "test_ecosystem_names_guard.py",
        "test_the_framework_source_names_no_ecosystem_outside_the_lists",
    ),
    ("test_live_split_names.py", "test_every_tagged_live_test_of_the_kit_is_in_one_derived_split"),
    ("test_live_test_names.py", "test_no_tracked_file_names_an_old_module"),
    (
        "test_live_tests_across_dimensions.py",
        "test_no_two_live_tests_of_the_kit_differ_in_name_only_by_a_dimension_value",
    ),
    (
        "test_live_tests_are_tagged.py",
        "test_every_test_of_the_kits_live_modules_that_starts_an_agent_has_exactly_one_tag",
    ),
    (
        "test_live_tests_are_tagged.py",
        "test_the_init_conventions_module_which_starts_no_agent_passes_untagged",
    ),
    (
        "test_live_tests_use_shared_tick.py",
        "test_each_live_test_that_runs_a_tick_ends_it_through_the_guarded_branch_check",
    ),
    (
        "test_live_tests_use_shared_tick.py",
        "test_no_live_test_defines_a_tick_result_runs_a_tick_or_reads_a_branch_with_bare_git",
    ),
    ("test_no_installation_leaks.py", "test_a_tracked_config_names_no_path_outside_the_checkout"),
    ("test_no_installation_leaks.py", "test_environment_is_read_only_through_the_settings_layer"),
    ("test_no_installation_leaks.py", "test_every_azure_organisation_belongs_to_a_fixture"),
    ("test_no_installation_leaks.py", "test_every_github_slug_belongs_to_a_fixture_owner"),
    ("test_no_installation_leaks.py", "test_no_dated_anecdotes"),
    ("test_no_installation_leaks.py", "test_no_home_directory_product_paths"),
    ("test_no_installation_leaks.py", "test_no_home_paths_in_text"),
    ("test_no_installation_leaks.py", "test_no_issue_or_pr_number_anecdotes"),
    ("test_no_installation_leaks.py", "test_no_personal_noreply_addresses"),
    ("test_no_live_policy_probe.py", "test_the_live_probe_and_its_remains_are_gone"),
    ("test_no_shared_session_ids.py", "test_no_session_id_is_defined_in_two_test_files"),
    ("test_old_test_kind_names_guard.py", "test_no_file_of_the_repository_names_the_rename_tool"),
    ("test_old_test_kind_names_guard.py", "test_the_repository_carries_no_old_spelling"),
    (
        "test_one_definition_per_pattern.py",
        "test_no_pattern_is_compiled_at_module_level_in_two_modules",
    ),
    ("test_path_discovery_git.py", "test_only_the_module_asks_git_for_the_root"),
    ("test_record_metric_guard.py", "test_no_function_but_the_helper_calls_the_local_record"),
    ("test_repo_wide_guards_use_the_helper.py", "test_no_test_module_walks_the_checkout_by_hand"),
    (
        "test_telemetry_marker.py",
        "test_a_split_on_the_marker_selects_the_otel_items_and_no_other_live_test",
    ),
    (
        "test_test_helpers_defined_once.py",
        "test_each_merged_helper_is_defined_only_in_a_shared_module",
    ),
    (
        "test_test_helpers_defined_once.py",
        "test_no_test_file_repeats_the_body_of_a_shared_helper_under_any_name",
    ),
    ("test_test_helpers_defined_once.py", "test_no_two_merged_helpers_share_a_name_and_a_body"),
    (
        "test_test_helpers_defined_once.py",
        "test_the_shared_commit_helper_is_not_copied_into_a_test_file",
    ),
    ("test_timing_guard.py", "test_the_suite_has_no_hazard_outside_the_allowlist"),
    (
        "test_verdict_readers_guard.py",
        "test_the_verdict_file_is_read_only_by_the_modules_the_spec_names",
    ),
]


@pytest.mark.parametrize(("module", "name"), WIDE_SCANS)
def test_a_test_that_scans_the_whole_repository_is_an_integration_test(
    pytester: pytest.Pytester, module: str, name: str
) -> None:
    items, _ = pytester.inline_genitems(str(ROOT / "tests" / module))
    named = [i for i in items if getattr(i, "originalname", i.name) == name]

    assert named, f"{module} has no test {name}"
    assert all(i.get_closest_marker("integration") is not None for i in named)


# A check of these modules also has `tmp_path` logic tests, which stay in the default run.
WITH_LOGIC_TESTS = [
    "test_timing_guard.py",
    "test_old_test_kind_names_guard.py",
    "test_ecosystem_names_guard.py",
    "test_no_shared_session_ids.py",
    "test_path_discovery_git.py",
    "test_child_pytest_sources_are_real_files.py",
]
DEFAULT_RUN = ["-m", "not integration and not local_stack"]


def test_the_baseline_holds_none_of_the_named_scans() -> None:
    named = {f"{module}::{name}" for module, name in WIDE_SCANS}

    assert sorted(named & load_baseline()) == []


def default_run_collects(pytester: pytest.Pytester, module: str) -> set[str]:
    """The names of the tests of a module that the default run selects: a collection that
    deselects by marker, which the items `inline_genitems` returns are not."""
    result = pytester.runpytest("--collect-only", "-q", *DEFAULT_RUN, str(ROOT / "tests" / module))
    return {line.split("::")[-1].split("[")[0] for line in result.outlines if "::" in line}


@pytest.mark.parametrize("module", sorted({module for module, _ in WIDE_SCANS}))
def test_the_default_run_collects_none_of_the_named_scans_of_a_module(
    pytester: pytest.Pytester, module: str
) -> None:
    collected = default_run_collects(pytester, module)

    assert collected.isdisjoint({name for owner, name in WIDE_SCANS if owner == module})


@pytest.mark.parametrize("module", WITH_LOGIC_TESTS)
def test_the_default_run_still_collects_the_logic_tests_of_a_check(
    pytester: pytest.Pytester, module: str
) -> None:
    assert default_run_collects(pytester, module)


@pytest.mark.integration
def test_no_test_of_the_repository_scans_it_without_the_integration_selector() -> None:
    assert check_tests(TESTS_ROOT, baseline=load_baseline()) == []
