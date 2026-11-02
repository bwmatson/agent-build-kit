"""A test that scans the whole source, test or repository tree runs under the loaded time limit.

Such a scan costs several times more under machine load and coverage tracing, so the default limit
fails it by chance. Add a scan here when it is found; the marker is on the test, never on a module's
`pytestmark`, so a fast fixture-tree test beside the scan keeps the default.
"""

from __future__ import annotations

import pytest

from tests.time_limit import LOADED_TEST_TIME_LIMIT, limit_for
from tests.tracked_files import ROOT

WIDE_SCANS = [
    (
        "tests/test_agent_call_rows.py",
        "test_the_guard_passes_over_the_real_source_with_an_empty_allowlist",
    ),
    (
        "tests/test_agent_call_guard.py",
        "test_every_agent_call_in_the_source_records_or_is_on_the_allowlist",
    ),
    (
        "tests/test_repo_wide_guards_use_the_helper.py",
        "test_no_test_module_walks_the_checkout_by_hand",
    ),
    (
        "tests/test_test_helpers_defined_once.py",
        "test_each_merged_helper_is_defined_only_in_a_shared_module",
    ),
    (
        "tests/test_test_helpers_defined_once.py",
        "test_the_shared_commit_helper_is_not_copied_into_a_test_file",
    ),
    (
        "tests/test_test_helpers_defined_once.py",
        "test_no_two_merged_helpers_share_a_name_and_a_body",
    ),
    (
        "tests/test_test_helpers_defined_once.py",
        "test_no_test_file_repeats_the_body_of_a_shared_helper_under_any_name",
    ),
    (
        "tests/test_child_pytest_sources_are_real_files.py",
        "test_the_repository_has_no_unlisted_or_stale_module",
    ),
    (
        "tests/test_one_definition_per_pattern.py",
        "test_no_pattern_is_compiled_at_module_level_in_two_modules",
    ),
    (
        "tests/test_no_live_policy_probe.py",
        "test_the_live_probe_and_its_remains_are_gone",
    ),
    (
        "tests/test_record_metric_guard.py",
        "test_no_function_but_the_helper_calls_the_local_record",
    ),
    (
        "tests/test_verdict_readers_guard.py",
        "test_the_verdict_file_is_read_only_by_the_modules_the_spec_names",
    ),
    (
        "tests/graph/test_verdict_is_shadow.py",
        "test_no_source_reads_the_verdict_file_outside_the_recording_module_and_status",
    ),
    (
        "tests/test_atomic_write_guard.py",
        "test_no_module_but_the_shared_one_replaces_a_file_from_a_temporary",
    ),
    (
        "tests/profiles/test_python_uv_e2e_summary_flags.py",
        "test_the_flags_are_named_in_the_python_profile_and_nowhere_else",
    ),
    (
        "tests/profiles/test_python_uv_e2e_durations.py",
        "test_the_flag_is_named_in_the_python_profile_and_nowhere_else",
    ),
    (
        "tests/pipeline/test_unit_causes.py",
        "test_no_module_still_has_a_deleted_note_matcher",
    ),
    (
        "tests/pipeline/test_unit_causes.py",
        "test_no_module_tests_a_note_by_its_prefix",
    ),
    (
        "tests/pipeline/test_config_unchanged_by_run.py",
        "test_there_is_no_config_changed_in_the_package",
    ),
    (
        "tests/pipeline/test_push_path_skips_red_check.py",
        "test_only_the_gate_command_calls_check_branch_so_a_real_test_and_an_empty_feat_can_push",
    ),
    (
        "tests/pipeline/test_planner_no_single_ceiling.py",
        "test_only_the_load_error_and_the_migration_name_the_setting",
    ),
    (
        "tests/runtimes/test_acp_known_agents.py",
        "test_no_framework_file_outside_the_table_names_a_product_from_it",
    ),
    (
        "tests/test_ecosystem_names_guard.py",
        "test_the_framework_source_names_no_ecosystem_outside_the_lists",
    ),
    (
        "tests/test_timing_guard.py",
        "test_the_suite_has_no_hazard_outside_the_allowlist",
    ),
    (
        "tests/test_no_shared_session_ids.py",
        "test_no_session_id_is_defined_in_two_test_files",
    ),
    (
        "tests/test_path_discovery_git.py",
        "test_only_the_module_asks_git_for_the_root",
    ),
    (
        "tests/test_live_test_names.py",
        "test_no_tracked_file_names_an_old_module",
    ),
    (
        "tests/test_old_test_kind_names_guard.py",
        "test_the_repository_carries_no_old_spelling",
    ),
    (
        "tests/test_old_test_kind_names_guard.py",
        "test_no_file_of_the_repository_names_the_rename_tool",
    ),
    ("tests/test_no_installation_leaks.py", "test_no_home_directory_product_paths"),
    ("tests/test_no_installation_leaks.py", "test_no_home_paths_in_text"),
    (
        "tests/test_no_installation_leaks.py",
        "test_every_github_slug_belongs_to_a_fixture_owner",
    ),
    (
        "tests/test_no_installation_leaks.py",
        "test_every_azure_organisation_belongs_to_a_fixture",
    ),
    ("tests/test_no_installation_leaks.py", "test_no_personal_noreply_addresses"),
    ("tests/test_no_installation_leaks.py", "test_no_issue_or_pr_number_anecdotes"),
    ("tests/test_no_installation_leaks.py", "test_no_dated_anecdotes"),
    (
        "tests/test_no_installation_leaks.py",
        "test_environment_is_read_only_through_the_settings_layer",
    ),
    (
        "tests/docs/test_review_docs_status.py",
        "test_no_document_names_a_removed_key_outside_the_migration",
    ),
    (
        "tests/docs/test_no_human_merges_every_pr.py",
        "test_no_markdown_file_states_a_person_merges_every_pull_request",
    ),
    (
        "tests/test_live_tests_use_shared_tick.py",
        "test_no_live_test_defines_a_tick_result_runs_a_tick_or_reads_a_branch_with_bare_git",
    ),
    (
        "tests/test_live_tests_use_shared_tick.py",
        "test_each_live_test_that_runs_a_tick_ends_it_through_the_guarded_branch_check",
    ),
    (
        "tests/test_agent_start_signals.py",
        "test_every_helper_module_that_starts_an_agent_is_in_the_table_or_excused_with_a_reason",
    ),
]


@pytest.mark.parametrize(("module", "name"), WIDE_SCANS)
def test_a_test_that_scans_the_whole_tree_runs_under_the_loaded_limit(
    pytester: pytest.Pytester, module: str, name: str
) -> None:
    items, _ = pytester.inline_genitems(str(ROOT / module))
    named = [item for item in items if item.originalname == name]  # type: ignore[attr-defined]

    assert named, f"{module} has no test named {name}"
    assert {limit_for(item) for item in named} == {LOADED_TEST_TIME_LIMIT}
