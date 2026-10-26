# Tasks

Acceptance: none — the rename changes names and nothing a consumer sees beyond them; the suite passing after every slice, the guard test and the idempotence of the tool are the proof, and each is a tier-1 test over temporary trees or the repository itself.

Priority: 1

## 1. [agent-build-kit] [unit-test] A tool renames the old spellings over the paths it is given, by token

Done when running the tool over a temporary tree rewrites identifiers, strings, comments, file names and Markdown from the table, running it again changes nothing, and it refuses a path outside its root, which is the framework repository. Estimate: about 330 changed lines.

Needs: test-kind-names-are-accepted-both-ways group 2 — the enum, the compatibility module and the reading of both spellings exist before anything is renamed

- [x] 1.1 Test: in `tests/test_rename_test_kinds.py`, over a temporary tree with `e2e_gate.py`, a class `E2eResult`, a constant `E2E_MARKER`, a string `"abk.e2e.test.time"`, a Markdown line `e2e-test results` and a test file `test_e2e_blocks.py`, the tool renames each to the form the table gives (`e2e_gate.py`, `E2eResult`, `E2E_MARKER`, `"abk.e2e.test.time"`, `e2e-test results`, `test_e2e_blocks.py`), and a path outside the repository is refused with nothing changed.
- [x] 1.2 Test: in `tests/test_rename_test_kinds_idempotent.py`, a second run over the same paths reports no file changed and writes none; a run over a path with only the compatibility module and its test leaves both untouched.
- [x] 1.3 Add the tool as a module that takes `--paths`, rewriting by token and not by substring so `unit` inside another word is unaffected, preserving case styles (`e2e-test`, `E2e`, `E2E`, `e2e-test`), renaming files with `git mv`, refusing a path outside the framework repository, and reporting the files it changed. (This is the first part of the former single task that also added `--root`, `--shims`, `--remove-shims` and `--dry-run`; those are task 2.3.)

## 2. [agent-build-kit] [unit-test] The tool leaves aliases behind, takes another root and can list its changes

Done when with shims the tool leaves each renamed module and symbol importable under its old name, `--remove-shims` deletes them, `--root` lets it run over a planning repository's Markdown and YAML, and `--dry-run` lists what it would change and writes nothing. Estimate: about 310 changed lines.

- [x] 2.1 Test: in `tests/test_rename_test_kinds_shims.py`, with shims a renamed module is left as a one-line module re-exporting the new one and each renamed class or constant is left bound under its old name in the new module's importers' paths, an import of the old names from an unconverted file succeeds, and `--remove-shims` deletes the aliases and the shim modules and an import of an old name then fails.
- [x] 2.2 Test: in `tests/test_rename_test_kinds_root.py`, run with another repository as its root over that repository's Markdown and YAML without shims, the tool rewrites `e2e_splits` to `e2e_splits` and `unit-test` to `unit-test` in them, renames no module, leaves code files alone when it is not given them, and refuses a path outside the root it was given.
- [x] 2.3 Add `--root`, `--shims`, `--remove-shims` and `--dry-run` to the tool (`--dry-run` lists what it would change and writes nothing). (This is the second part of the former single task that added the tool.)

## 3. [agent-build-kit] [unit-test] The pipeline package is renamed, files `archive.py` to `verify.py`

Done when the files `archive.py` to `verify.py` under `src/agent_build_kit/pipeline/` carry no old spelling, its four `e2e-test*` modules are `e2e*` with shims at the old names, callers elsewhere still import, and the suite passes. Estimate: about 430 changed lines.

- [x] 3.1 Test: in `tests/test_test_kind_rename_progress.py`, no file under `src/agent_build_kit/pipeline/` from `archive.py` to `verify.py` outside the shim modules contains an old spelling, and each old module name under it imports and gives the objects of the new one.
- [x] 3.2 Run the tool with shims over `src/agent_build_kit/pipeline/` for files from `archive.py` to `verify.py` in name order, review its result, and fix by hand only what it cannot rename (a name built from parts, a spelling inside a regular expression), recording each in the group's commit message.

## 4. [agent-build-kit] [unit-test] The pipeline package is renamed, files `wiring.py` to `workspaces.py`

Done when the remaining files of `src/agent_build_kit/pipeline/`, `wiring.py` to `workspaces.py`, carry no old spelling and the suite passes, so nothing under `pipeline/` carries one outside the shim modules. Estimate: about 370 changed lines.

- [x] 4.1 Test: extend `tests/test_test_kind_rename_progress.py` so every file under `src/agent_build_kit/pipeline/` is covered.
- [x] 4.2 Run the tool with shims over the files `wiring.py`, `work_graph.py` and `workspaces.py` of `src/agent_build_kit/pipeline/`, review its result, and fix by hand only what it cannot rename, recording each in the group's commit message.

## 5. [agent-build-kit] [unit-test] The source `cli/`, `config.py` and `forges/` are renamed

Done when `cli/`, `config.py` and `forges/` under `src/agent_build_kit/` carry no old spelling outside the compatibility module and the shims, the status context is `local/e2e-test`, the e2e-only settings, lock and status context are read for the e2e-test kind alone (a unit of the third kind, `integration-test`, is a unit-test there), and the suite passes. Estimate: about 440 changed lines.

Needs: integration-test-kind-is-a-label group 1 — the tests below build a unit of the `integration-test` kind, which the enum has only after that group

- [x] 5.1 Test: extend `tests/test_test_kind_rename_progress.py` so the same check covers `src/agent_build_kit/cli/`, `config.py` and `forges/`, and test in `tests/forges/test_e2e_status_context.py` that a unit's result is posted with the context `local/e2e-test` on the GitHub and Azure DevOps adapters, and that a unit of the `integration-test` kind is posted with no `local/e2e-test` status and takes no e2e lock and no `e2e_*` setting.
- [x] 5.2 Run the tool with shims over those paths, review its result, rename the settings fields, the flag `--e2e-test-time-limit` to `--e2e-test-time-limit` (the old flag still accepted with a notice), the lock file and the output directory (moved on first use when only the old one exists, a lock held under the old name honoured until released), and record in the group's commit message what it could not rename. Where this group's code tests for the e2e kind (the status context, the lock, the settings), test for `TestTier.E2E_TEST` alone, so a unit of any other kind is left out of those paths.

## 6. [agent-build-kit] [unit-test] The rest of the source, the web UI and the skill templates are renamed, `graph/` to `web/src`

Done when `graph/`, `infra/`, `init/`, `installation.py`, `profiles/`, `recommendations/`, `templates/`, `tracks/` under `src/agent_build_kit/` and `web/src` carry no old spelling outside the compatibility module and the shims, the node is `Node.E2E`, the metrics are `abk.e2e.*`, the rules text that `abk init` writes (`templates/openspec_rules.yaml`), the propose prompts (`init/propose.py`, `tracks/prompts/propose.md`) and the track and profile text name three kinds, `unit-test`, `integration-test` and `e2e-test`, each with what it covers, `[acceptance]` is still said to be e2e-test only, the graph's branches for the stack stay e2e-test only, and the suite passes. Estimate: about 325 changed lines.

Needs: integration-test-kind-is-a-label group 1 — the rules and prompts above name a tag that the group heading reader refuses until that group lands

- [x] 6.1 Test: extend `tests/test_test_kind_rename_progress.py` so the same check covers every source directory named above, the skill templates under `templates/` and `recommendations/`, and `web/src`; and test in `tests/templates/test_openspec_rules_test_kinds.py` that the rules text and the two propose prompts name `unit-test`, `integration-test` and `e2e-test` once each with a one-line meaning, say `integration-test` covers behaviour across modules in the ordinary suite with no live stack, say it is not the `integration` marker or `tests/integration/`, and say `[acceptance]` is `e2e-test`.
- [x] 6.2 Run the tool with shims over those paths, review its result, rename the node, record the metric renames in `tests/metric_names.py`, and write the three kinds into the rules and prompt texts named above. (The planner's prompt and its schema example are in `pipeline/planner.py`, which group 3 converts; `integration-test-kind-is-a-label` group 2 words them.)

## 7. [agent-build-kit] [unit-test] Test helpers at the top of `tests/`, files `calibration_support.py` to `time_split.py`

Done when the non-test modules at the top of `tests/` (the fakes, drivers and support files from `calibration_support.py` to `time_split.py`) carry no old spelling and are named for the new words, with shims at the old names, and the suite passes. Estimate: about 370 changed lines.

- [x] 7.1 Test: extend `tests/test_test_kind_rename_progress.py` to cover those files, and each old fake module name imports and gives the objects of the new one.
- [x] 7.2 Run the tool with shims over the files at the top of `tests/` that are not named `test_*.py` and carry an old spelling (`tests/*_fakes.py`, the `e2e_*` fakes, `runner_fakes.py`, `time_limit.py`, `time_split.py` and the other helpers), review its result, and fix by hand only what it cannot rename.

## 8. [agent-build-kit] [unit-test] Tests under `tests/pipeline`, files `test_call_record.py` to `test_planner_cycle_rule.py`

Done when those test files carry no old spelling and are named for the new words, and the suite passes. Estimate: about 420 changed lines.

- [x] 8.1 Test: extend `tests/test_test_kind_rename_progress.py` to cover those files.
- [x] 8.2 Run the tool with shims over `tests/pipeline/` for files from `test_call_record.py` to `test_planner_cycle_rule.py` in name order, review its result, and fix by hand only what it cannot rename.

## 9. [agent-build-kit] [unit-test] Tests under `tests/pipeline`, files `test_planner_project_check.py` to `test_task_progress.py`

Done when those test files carry no old spelling and are named for the new words, and the suite passes. Estimate: about 410 changed lines.

- [x] 9.1 Test: extend `tests/test_test_kind_rename_progress.py` to cover those files.
- [x] 9.2 Run the tool with shims over `tests/pipeline/` for files from `test_planner_project_check.py` to `test_task_progress.py` in name order, review its result, and fix by hand only what it cannot rename.

## 10. [agent-build-kit] [unit-test] Tests under `tests/pipeline`, files `test_unit_test_affected.py` to `test_e2e_gate_records.py`

Done when those test files carry no old spelling and are named for the new words, and the suite passes. Estimate: about 420 changed lines.

- [x] 10.1 Test: extend `tests/test_test_kind_rename_progress.py` to cover those files.
- [x] 10.2 Run the tool with shims over `tests/pipeline/` for files from `test_unit_test_affected.py` to `test_e2e_gate_records.py` in name order, review its result, and fix by hand only what it cannot rename.

## 11. [agent-build-kit] [unit-test] Tests under `tests/pipeline`, files `test_e2e_gate_wiring.py` to `test_e2e_scope_own.py`

Done when those test files carry no old spelling and are named for the new words, and the suite passes. Estimate: about 430 changed lines.

- [x] 11.1 Test: extend `tests/test_test_kind_rename_progress.py` to cover those files.
- [x] 11.2 Run the tool with shims over `tests/pipeline/` for files from `test_e2e_gate_wiring.py` to `test_e2e_scope_own.py` in name order, review its result, and fix by hand only what it cannot rename.

## 12. [agent-build-kit] [unit-test] Tests under `tests/pipeline`, files `test_e2e_scope_whole.py` to `test_wiring.py`

Done when those test files carry no old spelling and are named for the new words, and the suite passes. Estimate: about 410 changed lines.

- [x] 12.1 Test: extend `tests/test_test_kind_rename_progress.py` to cover those files.
- [x] 12.2 Run the tool with shims over `tests/pipeline/` for files from `test_e2e_scope_whole.py` to `test_wiring.py` in name order, review its result, and fix by hand only what it cannot rename.

## 13. [agent-build-kit] [unit-test] Tests under `tests/pipeline`, files `test_work_graph.py` to `test_workspaces.py`

Done when those test files carry no old spelling and are named for the new words, and the suite passes, so every file under `tests/pipeline/` is converted. Estimate: about 150 changed lines.

- [x] 13.1 Test: extend `tests/test_test_kind_rename_progress.py` so every file under `tests/pipeline/` is covered.
- [x] 13.2 Run the tool with shims over `tests/pipeline/` for files from `test_work_graph.py` to `test_workspaces.py` in name order, review its result, and fix by hand only what it cannot rename.

## 14. [agent-build-kit] [unit-test] Tests under `tests/graph`, files `test_adopted_event.py` to `test_open_pr_limit.py`

Done when those test files carry no old spelling and are named for the new words, and the suite passes. Estimate: about 330 changed lines.

- [x] 14.1 Test: extend `tests/test_test_kind_rename_progress.py` to cover those files.
- [x] 14.2 Run the tool with shims over `tests/graph/` for files from `test_adopted_event.py` to `test_open_pr_limit.py` in name order, review its result, and fix by hand only what it cannot rename.

## 15. [agent-build-kit] [unit-test] Tests under `tests/graph`, files `test_outside_commits_prompt.py` to `test_e2e_failure_log.py`

Done when those test files carry no old spelling and are named for the new words, and the suite passes. Estimate: about 330 changed lines.

- [x] 15.1 Test: extend `tests/test_test_kind_rename_progress.py` to cover those files.
- [x] 15.2 Run the tool with shims over `tests/graph/` for files from `test_outside_commits_prompt.py` to `test_e2e_failure_log.py` in name order, review its result, and fix by hand only what it cannot rename.

## 16. [agent-build-kit] [unit-test] Tests under `tests/graph`, files `test_e2e_feedback.py` to `test_verify_base_scope.py`

Done when those test files carry no old spelling and are named for the new words, and the suite passes. Estimate: about 310 changed lines.

- [x] 16.1 Test: extend `tests/test_test_kind_rename_progress.py` to cover those files, so every file under `tests/graph/` is covered.
- [x] 16.2 Run the tool with shims over `tests/graph/` for files from `test_e2e_feedback.py` to `test_verify_base_scope.py` in name order, review its result, and fix by hand only what it cannot rename.

## 17. [agent-build-kit] [unit-test] Tests under `tests/config`, `tests/fixtures`, `tests/forges` and `tests/init`

Done when `tests/config`, `tests/fixtures`, `tests/forges` and `tests/init` carry no old spelling, the fixtures (the recorded stores and the sample test reports) are renamed with their readers, and the suite passes. Estimate: about 260 changed lines.

- [x] 17.1 Test: extend `tests/test_test_kind_rename_progress.py` to cover those directories.
- [x] 17.2 Run the tool with shims over those directories, review its result, and fix by hand only what it cannot rename, including the recorded store and the sample test-report files the fixtures hold.

## 18. [agent-build-kit] [unit-test] Tests under `tests/integration`, `tests/profiles`, `tests/serve` and `tests/tracks`

Done when `tests/integration`, `tests/profiles`, `tests/serve` and `tests/tracks` carry no old spelling and are named for the new words, and the suite passes. Estimate: about 230 changed lines.

- [x] 18.1 Test: extend `tests/test_test_kind_rename_progress.py` to cover those directories.
- [x] 18.2 Run the tool with shims over those directories, review its result, and fix by hand only what it cannot rename.

## 19. [agent-build-kit] [unit-test] Tests under `tests/cli`

Done when every file under `tests/cli` carries no old spelling and is named for the new words, and the suite passes. Estimate: about 320 changed lines.

- [x] 19.1 Test: extend `tests/test_test_kind_rename_progress.py` to cover `tests/cli/`.
- [x] 19.2 Run the tool with shims over `tests/cli/`, review its result, and fix by hand only what it cannot rename.

## 20. [agent-build-kit] [unit-test] The remaining test files at the top of `tests/`, `test_config_restack_check.py` to `test_e2e_time_split.py`

Done when the `test_*.py` files at the top of `tests/`, from `test_config_restack_check.py` to `test_e2e_time_split.py`, carry no old spelling and are named for the new words, and the suite passes. Estimate: about 240 changed lines.

- [x] 20.1 Test: extend `tests/test_test_kind_rename_progress.py` so no file under `tests/` is left, outside the compatibility module's own test.
- [x] 20.2 Run the tool with shims over the `test_*.py` files at the top of `tests/`, review its result, and fix by hand only what it cannot rename.

## 21. [agent-build-kit] [unit-test] The documents under `docs/` are renamed

Needs: fix-flaky-tests-pipeline-test-moved-base-run-stored-py-test-a-e0297380 group 1 — flaky test tests/pipeline/test_moved_base_run_stored.py::test_a_running_pass_lets_a_handed_back_unit_in_and_still_refuses_the_causes_it_refused

Done when every document under `docs/` uses the new names, with no old spelling outside the philosophy and design documents' note on terminology, `docs/configuration.md` describes the new settings keys, `docs/architecture.md` lists the three kinds a group heading may carry (`unit-test`, `integration-test`, `e2e-test`) with what each covers and the order of their width, and the suite passes. Estimate: about 420 changed lines.

- [x] 21.1 Test: extend `tests/test_test_kind_rename_progress.py` and `tests/docs/` so every Markdown file under `docs/` is covered, with the two documents that explain the rename exempt by name, and test in `tests/docs/test_test_kinds_documented.py` that `docs/architecture.md` names the three tags, says `integration-test` covers behaviour across modules or files in the ordinary suite with no live stack and behaves as `unit-test` in every other way, says it is not the pytest `integration` marker or `tests/integration/`, and says a unit of several groups takes the widest kind.
- [x] 21.2 Run the tool over `docs/`, review its result, update `docs/configuration.md`, and word the three kinds in the section of `docs/architecture.md` that lists the tags (`unit-test` covers one module's behaviour, `integration-test` behaviour across modules or files with no live stack, `e2e-test` needs the real local stack; widths in that order).

## 22. [agent-build-kit] [unit-test] The README, AGENTS.md, the changelog and the three skills' text are renamed

Needs: fix-flaky-tests-pipeline-test-moved-base-run-stored-py-test-a-e0297380 group 1 — flaky test tests/pipeline/test_moved_base_run_stored.py::test_a_running_pass_lets_a_handed_back_unit_in_and_still_refuses_the_causes_it_refused

Done when `README.md`, `AGENTS.md` and the three skills' text (the source and the mirror) use the new names, the changelog has one entry for the rename that names the renamed metrics, flag, lock file and status context and says the old spellings are read for one release, and no document carries an old spelling outside the changelog's own entry and the philosophy and design documents' note on terminology; those texts say there are three kinds, `unit-test`, `integration-test` and `e2e-test`, with what each means, and the changelog entry says the third behaves as `unit-test`. Estimate: about 390 changed lines.

- [x] 22.1 Test: extend `tests/test_test_kind_rename_progress.py` and `tests/docs/` so every remaining Markdown file is covered, with the changelog entry exempt by name, and extend `tests/docs/test_test_kinds_documented.py` so that `README.md`, `AGENTS.md` and each of the three skills (source and mirror) name all three tags.
- [x] 22.2 Run the tool over those files, review its result, update the skills' tag guidance (`[<tier>]` as `[<kind>]`, the three tags and what each means: `unit-test` is one module's behaviour, `integration-test` behaviour across modules or files in the ordinary suite with no live stack, `e2e-test` needs the real local stack; `integration-test` is not the `integration` marker), and add the changelog entry, which also says `integration-test` is a label that behaves as `unit-test`.

## 23. [agent-build-kit] [unit-test] The aliases are removed and the guard is strict

Done when no shim module or alias remains, the guard test fails on any old spelling outside the compatibility module and its test, an import of an old name fails, and the tool stays, with its tests, for the person-run sweep of a planning repository's text, which is exempt from the guard while it exists. Estimate: about 330 changed lines.

- [x] 23.1 Test: in `tests/test_old_test_kind_names_guard.py`, a source, test or document file containing an old spelling fails the guard naming the file and line, the compatibility module, the rename tool and their tests are exempt, and the guard passes on the repository.
- [x] 23.2 Run the tool with `--remove-shims` over the whole tree, review its result, then delete the progress test and make the guard the only check left; the tool and its tests stay.
