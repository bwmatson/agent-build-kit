## Why

`tests/runtimes/test_policy_agent_harness.py::test_a_run_ended_once_the_agent_is_up_leaves_no_process_and_no_directory` failed under load and passed alone, twice, when run again by itself. A test like that fails units that did not touch it.

It ran as `uv run pytest -n auto --maxprocesses=8 -m '(not integration and not local_stack) and not serial' -q` and failed with:

```
>       return [int((record / name).read_text()) for name in ("agent.pid", "child.pid")]
                ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
E       ValueError: invalid literal for int() with base 10: ''

tests/runtimes/policy_fake_agents.py:67: ValueError
----------------------------- Captured stderr call -----------------------------
policy harness: heartbeat: still waiting, 0/3 judged
=============================== warnings summary ===============================
tests/test_claude_without_acp_gap_list.py::test_the_kits_current_list_matches_the_documents_without_a_warning
  /home/<redacted>/.local/share/<redacted>/worktrees/agent-build-kit/spec_a_unit_over_its_tier_is_held_and_split_8/tests/test_claude_without_acp_gap_list.py:131: UserWarning: test_chat_editing_claude_code.py::test_a_chat_edit_is_fixed_for_the_hook_committed_and_reviewed_without_a_round: a Claude scenario with no ACP sibling, not in agent-runtimes.md
    warn_gap_list_drift(items, DOCUMENT)

tests/test_claude_without_acp_gap_list.py::test_the_kits_current_list_matches_the_documents_without_a_warning
  /home/<redacted>/.local/share/<redacted>/worktrees/agent-build-kit/spec_a_unit_over_its_tier_is_held_and_split_8/tests/test_claude_without_acp_gap_list.py:131: UserWarning: test_chat_editing_claude_code.py::test_a_free_session_changes_code_and_a_task_file_and_each_checkout_is_committed: a Claude scenario with no ACP sibling, not in agent-runtimes.md
    warn_gap_list_drift(items, DOCUMENT)

tests/test_claude_without_acp_gap_list.py::test_the_kits_current_list_matches_the_documents_without_a_warning
  /home/<redacted>/.local/share/<redacted>/worktrees/agent-build-kit/spec_a_unit_over_its_tier_is_held_and_split_8/tests/test_claude_without_acp_gap_list.py:131: UserWarning: test_chat_editing_claude_code.py::test_a_request_against_a_requirement_is_flagged_and_changes_nothing: a Claude scenario with no ACP sibling, not in agent-runtimes.md
    warn_gap_list_drift(items, DOCUMENT)

tests/test_claude_without_acp_gap_list.py::test_the_kits_current_list_matches_the_documents_without_a_warning
  /home/<redacted>/.local/share/<redacted>/worktrees/agent-build-kit/spec_a_unit_over_its_tier_is_held_and_split_8/tests/test_claude_without_acp_gap_list.py:131: UserWarning: test_chat_editing_claude_code.py::test_a_stale_attachment_is_released_from_the_command_line: a Claude scenario with no ACP sibling, not in agent-runtimes.md
    warn_gap_list_drift(items, DOCUMENT)

tests/test_claude_without_acp_gap_list.py::test_the_kits_current_list_matches_the_documents_without_a_warning
  /home/<redacted>/.local/share/<redacted>/worktrees/agent-build-kit/spec_a_unit_over_its_tier_is_held_and_split_8/tests/test_claude_without_acp_gap_list.py:131: UserWarning: test_chat_editing_claude_code.py::test_the_next_rework_lists_the_outside_commit_as_authoritative: a Claude scenario with no ACP sibling, not in agent-runtimes.md
    warn_gap_list_drift(items, DOCUMENT)

tests/test_claude_without_acp_gap_list.py::test_the_kits_current_list_matches_the_documents_without_a_warning
  /home/<redacted>/.local/share/<redacted>/worktrees/agent-build-kit/spec_a_unit_over_its_tier_is_held_and_split_8/tests/test_claude_without_acp_gap_list.py:131: UserWarning: test_local_forge_unit.py::test_a_unit_is_reviewed_in_the_ui_reworked_approved_and_merged_by_a_person_with_git: a Claude scenario with no ACP sibling, not in agent-runtimes.md
    warn_gap_list_drift(items, DOCUMENT)

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
=========================== short test summary info ============================
FAILED tests/runtimes/test_policy_agent_harness.py::test_a_run_ended_once_the_agent_is_up_leaves_no_process_and_no_directory
1 failed, 12841 passed, 1 skipped, 6 warnings in 269.33s (0:04:29)

warning: `VIRTUAL_ENV=/home/<redacted>/<redacted>/.venv` does not match the project environment path `.venv` and will be ignored; use `--active` to target the active environment instead
```

It exercises `/home/<redacted>/.local/share/<redacted>/worktrees/agent-build-kit/spec_a_unit_over_its_tier_is_held_and_split_8/tests/runtimes/policy_agent_harness.py`, `/home/<redacted>/.local/share/<redacted>/worktrees/agent-build-kit/spec_a_unit_over_its_tier_is_held_and_split_8/tests/runtimes/policy_fake_agents.py`.

Times it flaked:

- 2026-10-22 14:37 UTC, unit a-unit-over-its-tier-is-held-and-split/8 (this one)

## What Changes

- `tests/runtimes/test_policy_agent_harness.py::test_a_run_ended_once_the_agent_is_up_leaves_no_process_and_no_directory` is made deterministic, whether the fault is in the test or in the code it exercises.

## Impact

- agent-build-kit: the test and, if it is the racy one, the module it exercises.
