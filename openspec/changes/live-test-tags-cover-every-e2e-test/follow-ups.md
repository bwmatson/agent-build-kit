## From `live-test-tags-cover-every-e2e-test/1`

- tests/test_live_tests_are_tagged.py:86 — The `agent_start_notes` warnings are emitted only after `assert drift(items) == []`, so on a failing run the notes, which could explain the failure, are never printed.

## From `live-test-tags-cover-every-e2e-test/6`

- tests/test_claude_without_acp_gap_list.py: the kit-level test is still named `test_the_kits_current_list_matches_the_documents_without_a_warning`. It can now pass while warning, so a name such as `test_the_kits_current_list_is_checked_against_the_document` would describe what it does.
