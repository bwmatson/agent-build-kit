## Why

`tests/cli/test_tick_scheduling_projects.py::test_one_project_starts_its_next_unit_as_one_of_its_builds_ends_and_the_other_does_not` failed under load and passed alone, twice, when run again by itself. A test like that fails units that did not touch it.

It ran as `uv run pytest -n auto --maxprocesses=8 -m '(not integration and not local_stack) and not serial' -q` and failed with:

```
[21:40:51] web3/1: open — open web3/1
[21:40:51] api1/1: open — open api1/1
[21:40:51] api2/1: open — open api2/1
[21:40:51] api3/1: open — open api3/1
[21:40:51] web2/1: open — open web2/1
[21:40:51] web4/1: open — open web4/1
[21:40:51] ready: web5/1, api5/1
[21:40:52] web5/1: open — open web5/1
[21:40:52] api5/1: open — open api5/1
=============================== warnings summary ===============================
tests/test_claude_without_acp_gap_list.py::test_the_kits_current_list_matches_the_documents_without_a_warning
  /home/<redacted>/.local/share/<redacted>/worktrees/agent-build-kit/spec_open_changes_are_migrated_to_review_tiers_6/tests/test_claude_without_acp_gap_list.py:131: UserWarning: test_chat_editing_claude_code.py::test_a_chat_edit_is_fixed_for_the_hook_committed_and_reviewed_without_a_round: a Claude scenario with no ACP sibling, not in agent-runtimes.md
    warn_gap_list_drift(items, DOCUMENT)

tests/test_claude_without_acp_gap_list.py::test_the_kits_current_list_matches_the_documents_without_a_warning
  /home/<redacted>/.local/share/<redacted>/worktrees/agent-build-kit/spec_open_changes_are_migrated_to_review_tiers_6/tests/test_claude_without_acp_gap_list.py:131: UserWarning: test_chat_editing_claude_code.py::test_a_free_session_changes_code_and_a_task_file_and_each_checkout_is_committed: a Claude scenario with no ACP sibling, not in agent-runtimes.md
    warn_gap_list_drift(items, DOCUMENT)

tests/test_claude_without_acp_gap_list.py::test_the_kits_current_list_matches_the_documents_without_a_warning
  /home/<redacted>/.local/share/<redacted>/worktrees/agent-build-kit/spec_open_changes_are_migrated_to_review_tiers_6/tests/test_claude_without_acp_gap_list.py:131: UserWarning: test_chat_editing_claude_code.py::test_a_request_against_a_requirement_is_flagged_and_changes_nothing: a Claude scenario with no ACP sibling, not in agent-runtimes.md
    warn_gap_list_drift(items, DOCUMENT)

tests/test_claude_without_acp_gap_list.py::test_the_kits_current_list_matches_the_documents_without_a_warning
  /home/<redacted>/.local/share/<redacted>/worktrees/agent-build-kit/spec_open_changes_are_migrated_to_review_tiers_6/tests/test_claude_without_acp_gap_list.py:131: UserWarning: test_chat_editing_claude_code.py::test_a_stale_attachment_is_released_from_the_command_line: a Claude scenario with no ACP sibling, not in agent-runtimes.md
    warn_gap_list_drift(items, DOCUMENT)

tests/test_claude_without_acp_gap_list.py::test_the_kits_current_list_matches_the_documents_without_a_warning
  /home/<redacted>/.local/share/<redacted>/worktrees/agent-build-kit/spec_open_changes_are_migrated_to_review_tiers_6/tests/test_claude_without_acp_gap_list.py:131: UserWarning: test_chat_editing_claude_code.py::test_the_next_rework_lists_the_outside_commit_as_authoritative: a Claude scenario with no ACP sibling, not in agent-runtimes.md
    warn_gap_list_drift(items, DOCUMENT)

tests/test_claude_without_acp_gap_list.py::test_the_kits_current_list_matches_the_documents_without_a_warning
  /home/<redacted>/.local/share/<redacted>/worktrees/agent-build-kit/spec_open_changes_are_migrated_to_review_tiers_6/tests/test_claude_without_acp_gap_list.py:131: UserWarning: test_local_forge_unit.py::test_a_unit_is_reviewed_in_the_ui_reworked_approved_and_merged_by_a_person_with_git: a Claude scenario with no ACP sibling, not in agent-runtimes.md
    warn_gap_list_drift(items, DOCUMENT)

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
=========================== short test summary info ============================
FAILED tests/cli/test_tick_scheduling_projects.py::test_one_project_starts_its_next_unit_as_one_of_its_builds_ends_and_the_other_does_not
1 failed, 12479 passed, 1 skipped, 6 warnings in 460.18s (0:07:40)

warning: `VIRTUAL_ENV=/home/<redacted>/<redacted>/.venv` does not match the project environment path `.venv` and will be ignored; use `--active` to target the active environment instead
```

It exercises `/home/<redacted>/.local/share/<redacted>/worktrees/agent-build-kit/spec_open_changes_are_migrated_to_review_tiers_6/src/agent_build_kit/cli/__init__.py`, `/home/<redacted>/.local/share/<redacted>/worktrees/agent-build-kit/spec_open_changes_are_migrated_to_review_tiers_6/src/agent_build_kit/pipeline/unit_store.py`, `/home/<redacted>/.local/share/<redacted>/worktrees/agent-build-kit/spec_open_changes_are_migrated_to_review_tiers_6/src/agent_build_kit/pipeline/units.py`, `/home/<redacted>/.local/share/<redacted>/worktrees/agent-build-kit/spec_open_changes_are_migrated_to_review_tiers_6/tests/conftest.py`, `/home/<redacted>/.local/share/<redacted>/worktrees/agent-build-kit/spec_open_changes_are_migrated_to_review_tiers_6/tests/factories.py`, `/home/<redacted>/.local/share/<redacted>/worktrees/agent-build-kit/spec_open_changes_are_migrated_to_review_tiers_6/tests/tick_driver.py`, `/home/<redacted>/.local/share/<redacted>/worktrees/agent-build-kit/spec_open_changes_are_migrated_to_review_tiers_6/tests/tick_pass.py`.

Times it flaked:

- 2026-10-22 03:47 UTC, unit open-changes-are-migrated-to-review-tiers/6 (this one)

## What Changes

- `tests/cli/test_tick_scheduling_projects.py::test_one_project_starts_its_next_unit_as_one_of_its_builds_ends_and_the_other_does_not` is made deterministic, whether the fault is in the test or in the code it exercises.

## Impact

- agent-build-kit: the test and, if it is the racy one, the module it exercises.
