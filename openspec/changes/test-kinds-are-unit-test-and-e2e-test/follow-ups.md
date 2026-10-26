## From `test-kinds-are-unit-test-and-e2e-test/2`

- tests/test_rename_test_kinds_shims.py:115 — The top-level shim test only checks that `import e2e_gate` exits 0. It does not check that the old name is bound to the renamed module.
- src/agent_build_kit/rename_test_kinds.py:160 — The `rename_paths` docstring was rewrapped unevenly: one line ends at `remove_shims deletes those instead` and is much shorter than the lines around it.

## From `test-kinds-are-unit-test-and-e2e-test/3`

- tests/cli/test_tick_scheduled_e2e.py:90 compares the lock files before and after the dry run, and only fails on a new lock whose name contains "scheduled". If the schedule lock is ever renamed without that word, the check becomes vacuous again. Deriving the expected name from `e2e_schedule.PREFIX`, or exposing the lock path as a named constant that the test imports, would tie the check to the code.

## From `test-kinds-are-unit-test-and-e2e-test/4`

- Two things for the units that convert `profiles/` and add the final guard. First, when `profiles/` is converted, replace `_E2E_COMMANDS = "tier" + "2_commands"` and its `getattr` in `wiring.py` `e2e_work` with a direct `toolchain.e2e_commands(where, marker=marker)` call. Rework commit 19bf86de records this, and so does the comment above the constant. Second, the final guard's pattern should also match the hyphenated `tier-[12]` spellings still present in comments and help text in `python_uv.py`, `config.py`, `settings.py`, `replay/__init__.py` and `cli/replay_cmd.py`.

## From `test-kinds-are-unit-test-and-e2e-test/5`

- tests/pipeline/test_e2e_lock_old_name.py:1 — The module docstring still says the old lock is "removed once taken". Since the round-2 rework that is no longer true: the file now stays on disk, and the second test checks that it does.

## From `test-kinds-are-unit-test-and-e2e-test/6`

- The new changelog sentence ('Upgrade while no tick is running: …') is run onto the end of the existing line and goes well past the wrap width the rest of the bullet uses. Rewrap it with the two-space continuation.

## From `test-kinds-are-unit-test-and-e2e-test/8`

- tests/pipeline/test_redaction_store_and_logs.py: the renamed test `test_a_failed_redaction_logs_one_line_for_a_e2e_of_several_commands` should say `an_e2e`, as the other renames in this commit do (for example `test_an_e2e_failure_after_a_scoped_flake...`).

## From `test-kinds-are-unit-test-and-e2e-test/12`

- The progress guard's OLD_SPELLING (`tier[-_ ]?[12]`) does not match spelled-out forms such as `tier_one` or `tier_two`. In this unit, test names with those words were renamed by hand rather than caught by the guard. Later graph units (groups 15 and on, e.g. `tests/graph/test_e2e_failure_log.py:28` and `test_remaining_paths.py`, `test_span_records.py`, `test_stack_scenarios.py`) would be protected if the pattern also matched `tier[-_ ]?(one|two)`.

## From `test-kinds-are-unit-test-and-e2e-test/15`

- tests/graph/test_stack_scenarios.py:202 — Some mechanically renamed test names read awkwardly: `test_a_unit_test_unit_does_not_touch_the_local_stack`, `test_a_commit_unit_test_makes_before_the_review_is_the_commit_that_is_reviewed`, and `test_the_restacks_unit_test_is_the_setting_of_the_repo_the_branch_is_in` in tests/cli/test_restack_wiring.py:101.

## From `test-kinds-are-unit-test-and-e2e-test/18`

- tests/parked_split_support.py:84 — The rework changed the note `park()` writes from `e2e-test tests of ... did not run: the split is held` to `e2e tests of ...`. The production note at src/agent_build_kit/graph/nodes.py:1345 still says `e2e-test tests of {waiting} did not run: the split is held`.

## From `test-kinds-are-unit-test-and-e2e-test/21`

- src/agent_build_kit/skills/abk-authoring/SKILL.md:12 — Fixing the doubled word left one line of about 140 characters, while the rest of the paragraph wraps at about 78. docs/configuration.md:390 is in the same state: the re-wrapped comment line runs a few columns past the comment block's margin.

## From `test-kinds-are-unit-test-and-e2e-test/23`

- tests/profiles/test_node_npm_e2e.py:115 — The renamed test `test_a_marker_not_right_before_test_is_a_e2e_file_for_neither_run` reads 'an e2e', which is ungrammatical. The other renames in this commit read cleanly.
