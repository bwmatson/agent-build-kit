# Tasks

Acceptance: none — the tags, the selection, the held set, the parking and the splits' scheduled changes are decided by a temporary git repository, a fake test runner, a temporary planning directory, collection of fixture test files and the fake graph the e2e-test node tests use; the kit's own live-stack tests this change tags and splits are the live confirmation, and each runs for real when its group is built.

Priority: 2

## 1. [agent-build-kit] [unit-test] A live-stack test names the runtime it drives with one tag, and a wrong tag fails collection

Done when `runtime_claude_code` and `runtime_acp` are registered markers beside a registered `dev_stack`, marker typos fail collection, a live-stack test that carries two or more runtime tags fails collection naming it, a test with none is the untagged base, and a drift test ties the registered tags to the runtime registry. Estimate: about 250 changed lines.

- [x] 1.1 Test: `tests/test_runtime_tags_registered.py` asserts the project's registered markers hold exactly one `runtime_<name>` for each runtime name the registry knows plus the protocol runtime's name, and `dev_stack`, that the default options turn strict markers on, and, over a collected fixture file, that a test marked `runtime_typo` fails collection naming the marker.
- [x] 1.2 Test: `tests/test_runtime_tag_rule.py` collects fixture files and asserts a live-stack test with two different runtime tags (both on the test, one on its class or module and one on the test, or one on a parameter and one on the module) fails collection with an error naming the test and both tags, that one tag collects, that none collects, that the same tag twice collects, and that a test that is not live-stack with two tags is not checked.
- [x] 1.3 Test: the same file asserts a parametrised live-stack test whose parameters each carry one different runtime tag collects as separate items each with its one tag, and that a parameter tag plus a module tag fails naming the item.
- [x] 1.4 Register the runtime tags and `dev_stack` in the project's marker list, turn strict markers on in the default options, and add the collection-time check as a test plugin beside the time-limit plugin, listed in the shared test configuration.
- [x] 1.5 Run the whole default suite with strict markers on and register or correct any marker it uses that was never registered, so nothing else fails collection.

## 2. [agent-build-kit] [unit-test] One builder makes the e2e-test selection and every e2e-test command takes it

Done when a single function builds the e2e-test marker expression from the repo's marker and the set of blocked runtimes (and, for a resume or a scheduled variant, the one group to run alone), the python profile's e2e-test, acceptance, own-scope repeat and base re-run commands all carry the expression and the base re-run keeps it, the profile can list which tests an expression selects in a command, and a run that cannot express the selection says so. Estimate: about 340 changed lines.

- [x] 2.1 Test: `tests/pipeline/test_e2e_selection.py` asserts the expression is the marker alone when nothing is blocked, is the marker and `not` each blocked runtime's tag when some are, is the marker and the tag when one runtime is asked for alone, and is the marker and `not` every known runtime's tag when the base group is asked for alone, that a runtime name the registry and the configuration do not know is refused naming it, that the name `base` cannot be blocked, and that the same inputs always give the same text.
- [x] 2.2 Test: `tests/profiles/test_python_uv_e2e_selection.py` asserts `e2e_commands` and `acceptance_commands` carry the given expression after `-m` for the root and for each member (the acceptance one still adding the dev stack exclusion), that `repeat_command` keeps it under the selected identifiers, and that `serial_rerun_command` keeps `-m <expression>` while still dropping the command's workers and paths, and is unchanged for a command with no `-m`.
- [x] 2.3 Test: the same file asserts the profile's listing hook returns the identifiers an expression selects in a command, given a fake runner printing a collection listing, narrows to given identifiers, returns nothing selected for the empty listing, and returns an unknown (not an empty list) when the listing fails, and that a profile without the hook, the node profile and a repo whose e2e-test runs through its dev stack script are reported as unable to express a selection.
- [x] 2.4 Add the builder as a pure function beside the e2e-test session, taking the repo's marker and the blocked set and returning the expression with the runtimes it leaves out and the group it runs alone; the known runtimes come from the registry, the protocol runtime's name and the configured runtime keys.
- [x] 2.5 Make the python profile's base re-run keep the expression and add the optional listing hook to the profile protocol and the python profile; the profiles that cannot express a selection report it by the hook's absence.

## 3. [agent-build-kit] [unit-test] The configuration names the runtimes that are blocked, allowed and run by the schedule

Done when `abk.yaml` takes `tests.runtimes_blocked`, `tests.runtimes_allowed` and `tests.e2e_runtimes` at the top of the file and a repo's own `tests.e2e_runtimes`, each a list of runtime names, refused when it names an unknown runtime, `base` or a name in both the blocked and allowed lists, and `abk config --show` prints them. Estimate: about 230 changed lines.

- [x] 3.1 Test: `tests/config/test_e2e_runtimes_config.py` asserts the three lists default to empty, that each accepts the names of the registry's runtimes, the protocol runtime and the runtimes the file configures under `runtimes`, and that an unknown name, the name `base` or a duplicated name is refused with a message naming the setting and the runtimes there are.
- [x] 3.2 Test: the same file asserts a runtime named in both `tests.runtimes_blocked` and `tests.runtimes_allowed` is refused naming both settings, and that a configuration with only one of them loads.
- [x] 3.3 Test: the same file asserts `repos.<name>.tests.e2e_runtimes` is unset by default, that one function gives a repo's variants as `base` followed by its own list when set and the top-level list otherwise, and that `abk config --show` prints the lists set.
- [x] 3.4 Add the top-level `tests` block with the three lists and the repo's optional `e2e_runtimes`, the validation, the one function that reads a repo's variants, and the `abk config --show` lines.

## 4. [agent-build-kit] [unit-test] The blocked set is the configuration and the state file together, and the configuration wins

Done when one function says which runtimes are blocked now from the `tests` lists and a `e2e-blocked.json` file in the state directory, a runtime the configuration allows is not blocked whatever the file says, a runtime the configuration blocks is blocked whatever the file says, an expired deadline lifts a block, and the file is written atomically under a lock. Estimate: about 270 changed lines.

- [x] 4.1 Test: `tests/pipeline/test_e2e_blocks.py` asserts a runtime listed in `tests.runtimes_blocked` is blocked with no file, a runtime in the file is blocked with no configuration, a runtime in both is blocked once with both origins named, and a runtime in neither is not.
- [x] 4.2 Test: the same file asserts the configuration wins both ways: a runtime the file blocks and `tests.runtimes_allowed` lists is not blocked and the result names the file's entry as overridden, and a runtime the configuration blocks stays blocked when the file holds no entry or an expired one.
- [x] 4.3 Test: the same file asserts a file entry with an `until` in the past or exactly now no longer blocks, one in the future still does and reports the deadline, one with none never expires, an entry whose source is `command` never carries one (the file's writer refuses it), a configuration entry never expires, and that reading changes nothing on disk.
- [x] 4.4 Test: the same file asserts the file's entries carry the reason, the time it was written, the optional deadline (written only by the provider and availability sources), the source (`command`, `provider` or `availability`) and who wrote it, that a file that cannot be read blocks nothing and is reported as unreadable, that an entry naming a runtime nothing knows is ignored and reported, and that two writers at once leave a file holding both entries.
- [x] 4.5 Add the file's model, its read and its atomic write under a lock beside the pause marker's, and the one function that returns the blocked runtimes with their reasons, deadlines and origins from the configuration, the file and the clock.

## 5. [agent-build-kit] [unit-test] A runtime can be added to or removed from the configuration's blocked list by editing the file as text

Done when a function adds a runtime to or removes it from `tests.runtimes_blocked` and `tests.runtimes_allowed` in `abk.yaml` by inserting or deleting lines, so every comment and every other line stays as it was, copies the original once to a backup beside it, writes through a temporary file, and refuses with the reason when the file cannot be changed that way. Estimate: about 280 changed lines.

- [x] 5.1 Test: `tests/config/test_config_text_edit.py` asserts adding a name to a file with no `tests` block appends the block, adding to a `tests` block without the list inserts the key at the block's indentation, adding to a block list appends an item in the list's own indentation and quoting, and adding to a one-line flow list or an empty one edits it in place, with every other line, comment and line ending of the file unchanged.
- [x] 5.2 Test: the same file asserts removing a name deletes only its item, leaves `[]` when it was the last, does nothing and says so when the name is absent, and that adding a name already present changes nothing.
- [x] 5.3 Test: the same file asserts a file with a duplicate `tests` key, an anchor or alias on the list, a multi-line flow list, a list that is not a list, text that does not parse, or a `tests` mapping written in flow style is refused with the reason named and is left byte for byte as it was, and that a read-only file is refused the same way.
- [x] 5.4 Test: the same file asserts the original is copied once to a backup beside the file and a later edit leaves that first backup alone, that the result is reloaded and an edit whose result does not give the expected lists is refused and not written, and that the file keeps its mode.
- [x] 5.5 Add the edit function beside the loader, reusing the policy command's backup suffix and replace-through-a-temporary-file technique.

## 6. [agent-build-kit] [unit-test] `abk e2e-test hold`, `release` and `status` change both places and show what is held

Needs: tier2-splits-replace-runtime-tags group 5 — builds on the split code, not the runtime names

Needs: test-kind-names-are-accepted-both-ways group 2 — build on the new test-kind names: spell anything you introduce `unit-test` or `e2e-test` (settings `e2e_*` and `unit_test_*`) unless this change's spec fixes the spelling; the old `unit-test` and `e2e-test` spellings still read, with a notice

Done when `abk e2e-test hold <split> [--reason TEXT]` (no deadline: a hand-set hold ends only with `release`), `release <split>` and `status` join `check` in the `e2e-test` command group and write the state file `e2e-held.json` and the split's `hold` in the configuration together, both or neither, refuse and change nothing when the configuration cannot be edited, and `abk status` and `abk doctor` show every held split and a conflict between the file and the configuration. Estimate: about 330 changed lines.

- [x] 6.1 Test: `tests/cli/test_e2e_cmd.py` asserts `hold acp --reason R` sets `hold: true` on every declaration of the split `acp` (removing a `hold: false` it finds), writes the file entry with the reason, the time, no deadline field, the source `command` and the user, in one operation, says what it changed, that a second `hold` updates the reason instead of adding a second entry, and that `rest` can be held and appends `rest: {hold: true}`.
- [x] 6.2 Test: the same file asserts `hold` has no `--until` argument (giving one exits 2 as an unknown argument) and that a hold it writes stays until `release`.
- [x] 6.3 Test: the same file asserts `release acp` removes the entry and the `hold: true` line from both places, that it says plainly when the split is still held afterwards by a `gate` entry its gate may write again or by a hand-written configuration line it could not remove, that a name that is neither a declared split nor `rest` exits 2 naming the splits there are, and that releasing a split that is not held says so and changes nothing.
- [x] 6.4 Test: the same file asserts that when the configuration cannot be edited (a flow-style or multi-line entry, an anchor, an unreadable or unwritable file) `hold` and `release` write nothing at all, neither the state file nor the configuration, exit non-zero, and print exactly why and the line to add or remove by hand.
- [x] 6.5 Test: `tests/cli/test_e2e_status_lines.py` asserts `abk e2e-test status` lists each declared split and `rest` as usable or held with its reason, source, deadline and origin, shows a split the configuration releases (`hold: false`) although the file holds it, and shows the splits the schedule will run; that `abk status` prints one line per held split and none when nothing is held; and that `abk doctor` reports held splits as information, a file-versus-configuration conflict as a warning, and an unreadable file as a failure.
- [x] 6.6 Add `hold`, `release` and `status` to the `e2e-test` command group's module that group 3 of `tier2-splits-replace-runtime-tags` created, over its `set_hold` text edit and the held set's `write_hold` and `remove_hold`, and the status and doctor lines.

## 7. [agent-build-kit] [unit-test] An e2e-test run executes the groups that can run, names the ones it cannot, and attributes a failure to its runtime

Done when an e2e-test run leaves out the blocked runtimes through the one expression, finds by listing which blocked runtimes hold a test the run would have executed and reports them as parked on its result, never reports a parked run as a complete pass, attributes each failed test to its runtime group, keeps the expression in the base re-run, and runs the whole repo with a stated reason where the selection cannot be expressed. Estimate: about 340 changed lines.

- [x] 7.1 Test: `tests/pipeline/test_e2e_runtime_groups.py` runs `E2eSession` over a temporary git repository with a fake runner and asserts that with acp blocked every command carries an expression that leaves out acp, that the blocked group is listed under the same expression's opposite and reported on the result as parked only when the listing finds a test of it (among the unit's own identifiers under own scope, among all under full), and that nothing blocked runs one command per project exactly as before.
- [x] 7.2 Test: the same file asserts a result with a parked runtime is not a complete pass (its snapshot and status description name the parked runtime and never say the suite passed), that a parked group with nothing else to run runs no command and takes no lock, and that a listing that fails parks the group and says why instead of running it.
- [x] 7.3 Test: the same file asserts each failed test of a run carries its runtime group (`base` or the runtime), found by listing the failed identifiers under each runtime's tag, that a failure whose group cannot be found is marked unknown and is not classified, and that the base re-run of a failed test keeps the run's expression.
- [x] 7.4 Test: the same file asserts a repo that runs e2e-test through its dev stack script runs whole with a blocked runtime, says in its log that the script cannot leave the runtime out, and a run limited to one group (a resume) runs only that group's expression.
- [x] 7.5 Add the blocked set to the e2e-test session, the expression to the scope decision and the commands it builds, the parked runtimes and each failure's group to the result and the scope, and the one-group run for a resume.

## 8. [agent-build-kit] [unit-test] A unit whose own tests include a parked group waits for the runtime and resumes only that group

Done when a unit whose e2e-test run passed what it could run and parked a blocked runtime's tests is held planned with the runtime named, without a rework round, a feedback, a failure record, a fix change or a status for tests that did not run, and when it resumes it runs only the parked group on the same commit, or the whole run if the commit moved. Estimate: about 320 changed lines.

- [x] 8.1 Test: `tests/graph/test_e2e_runtime_park.py` drives the e2e-test node with a fake runner whose result parks acp and asserts the unit is held planned with the cause `runtime_blocked`, a note naming acp and the block's reason, the parked runtimes and the commit that ran stored, no feedback saved, no fix round counted, no failure recorded, no fix change written and no status posted.
- [x] 8.2 Test: the same file asserts a unit with no own test in the blocked group is not held, that a unit whose other groups failed fails as before and is not parked, and that a unit parked on two runtimes names both.
- [x] 8.3 Test: the same file asserts the resumed node runs only the parked group's expression on the stored commit, adds the first run's result to the snapshot it posts, posts its status only when both runs passed, parks again when the group is still blocked, runs the whole expression when the head is not the stored commit, and clears the stored parking when it passes.
- [x] 8.4 Test: `tests/pipeline/test_e2e_status_not_green.py` asserts the status posting refuses a result with a parked runtime (nothing is sent) and that a unit parked before its push has no commit on the host to carry a status.
- [x] 8.5 Add the cause and the stored parked runtimes and commit, the park in the e2e-test node and the resume with its one-group run, and the guard in the status posting.

## 9. [agent-build-kit] [unit-test] A parked unit is released when its splits are usable and shown while it waits

Needs: tier2-splits-replace-runtime-tags group 7 — builds on the split code, not the runtime names

Done when a pass step beside the release of gated units resumes each unit parked with the cause `split_held` once none of the splits it waits on is held, a parked unit shows in `abk status` waiting for e2e-test split `<name>` with the reason and the deadline and holds no place against the unit limit, and a tick with only parked units is not idle. Estimate: about 250 changed lines.

- [x] 9.1 Test: `tests/pipeline/test_release_split_held.py` asserts a planned unit with the cause `split_held` whose splits are all usable is resumed once through the same delivery the gated units use, one whose splits are still held or only partly usable is left, a unit in flight or on a busy branch is skipped, and a step that raises is logged and the rest run.
- [x] 9.2 Test: the same file asserts the release follows the configuration (a split with `hold: false` releases the unit although the file holds it) and an expired deadline on a `gate` entry (the unit is released on the first pass after it), and that a unit is released once per hold, not on every pass.
- [x] 9.3 Test: `tests/cli/test_status_parked_units.py` asserts `abk status` lists a parked unit as waiting for e2e-test split `<name>` with its reason and deadline, that it is not counted against `max_units_in_progress`, and that `abk tick --dry-run` says which parked units would be released.
- [x] 9.4 Test: `tests/cli/test_tick_parked_work.py` asserts a tick whose only work is a parked unit is not idle and runs the release step, that the step reads only the state file and the configuration (no gate is evaluated), and that a tick with nothing waiting returns idle as before.
- [x] 9.5 Add the release step to the round, the status lines and the dry-run lines.

## 10. [agent-build-kit] [unit-test] A failure and the gate belong to a runtime, and a blocked runtime never records a failure

Done when the record of failures that also fail on the base carries the runtime group of the failing test (`base` for an entry written before), the open-fix gate holds a run only for an open fix whose group the run would execute, a blocked runtime's tests never run so never record or write a fix change, and the written fix change names the runtime. Estimate: about 270 changed lines.

- [x] 10.1 Test: `tests/pipeline/test_untouched_failures_runtime.py` asserts an entry recorded for a failure of acp carries `acp`, one recorded before this change reads as `base`, that the fix change written for it names the runtime in its proposal, and that two failures of the same test in different runtimes are two entries.
- [x] 10.2 Test: the same file asserts the gate holds a full run for an open fix recorded for `base` or for a runtime the run executes, does not hold a run that executes only claude_code for an open acp fix, does not hold a run that left a blocked runtime out for that runtime's fix, still holds only units of the entry's repo, and still exempts the fix change's own unit and a unit already waiting on it.
- [x] 10.3 Test: `tests/graph/test_e2e_runtime_gate.py` drives the node with a fake runner and asserts an acp failure of an unblocked run is recorded with its runtime and parks the unit as before, that a failure whose runtime is unknown is the unit's own failure with the output as feedback and no record, and that a blocked runtime with failing tests records nothing and writes no `fix-failing` change.
- [x] 10.4 Add the runtime to the record's entry, the runtimes the run executes to the scope decision the gate asks, the filter in the gate's lookup, and the runtime line in the written fix change.

## 11. [agent-build-kit] [unit-test] Post-merge verification waits for a held split instead of passing without it

Needs: tier2-splits-replace-runtime-tags group 6 — builds on the split code, not the runtime names

Done when the post-merge live check takes the same selection, leaves the held splits out, and when a held split holds a live test among the change's files skips the verification for this round without a record or a deploy, as it already does when the stack is busy, and runs it once the split is released. Estimate: about 200 changed lines.

- [x] 11.1 Test: `tests/pipeline/test_verify_split_holds.py` asserts the acceptance commands of the verification carry the selection with the held splits left out, that nothing held gives the commands it gave before, and that a repo with no declared split is unaffected.
- [x] 11.2 Test: the same file asserts that when a held split holds a live test among the change's files the verification deploys nothing, runs nothing, records nothing, logs that it was skipped for the split and is tried again the next round, and that the change is not archived meanwhile.
- [x] 11.3 Test: the same file asserts that when the split is released the verification runs and records as before, and that a held split with no test among the change's files does not delay it.
- [x] 11.4 Add the selection to the verification's commands and the skip for a held split beside the busy-stack skip.

## 12. [agent-build-kit] [unit-test] The scheduled run is one change per variant, and each variant is due and open on its own

Done when a due repo gets one `scheduled-e2e-<repo>-<date>-<variant>` change for each variant it runs (the base group plus each runtime its `e2e_runtimes` names), the due check and the open check are per repo and variant, a variant's change is written with the variant named in its proposal and its task, and a variant that is blocked keeps its change open while the others are written and run. Estimate: about 290 changed lines.

Needs: tier2-runs-on-a-schedule group 2 — the due check, the name and the written change this group splits by variant

- [x] 12.1 Test: `tests/pipeline/test_scheduled_e2e_variants.py` asserts a due repo with `e2e_runtimes` of acp and claude_code gets three changes named `scheduled-e2e-<repo>-<today>-base`, `-acp` and `-claude_code`, that a repo with no list gets only the base one, that `off` writes none, and that a repo whose own `tests.e2e_runtimes` is set uses it instead of the top-level list.
- [x] 12.2 Test: the same file asserts the due date of a variant is read from the latest change of that repo and variant, open or archived, so a variant never run is due at once while the others wait out their period, that a name with no variant suffix reads as the base variant, that a repo whose name begins another's and a variant whose name begins another's are not confused, and that the date and the variant are read from the name and nothing is stored.
- [x] 12.3 Test: the same file asserts no second change is written for a (repo, variant) while one is open, that a variant's open change does not stop the other variants' changes, that five missed periods write one change per variant and a second round writes none, and that two writers at once write one change per variant.
- [x] 12.4 Test: the same file asserts each written change passes `abk check` and `abk tags`, names the variant in its proposal, design and task, has one group at priority 3 with its `Separate:` line, and that a blocked variant's change is written like the others and stays open.
- [x] 12.5 Make the name carry the variant and read it back, make the due and open checks take the variant, write one change per variant, and take the variants from the repo's resolved list.

## 13. [agent-build-kit] [unit-test] A scheduled split's unit runs its own split and waits, change open, while the split is held

Needs: tier2-splits-replace-runtime-tags group 9 — builds on the split code, not the runtime names

Done when the unit of a split's scheduled change runs the whole marker restricted to its split on the default branch, passes as a satisfied unit with a note naming the split, parks with the split named while it is held and resumes when it is released, and a failing test of the split is recorded for that split and fixed once. Estimate: about 260 changed lines.

- [x] 13.1 Test: `tests/graph/test_scheduled_e2e_split_unit.py` drives the node with a fake runner and asserts the unit of a `-rest` change runs the selection of `rest` alone, that of a `-claude_code` change that split's selector alone, that a pass ends it satisfied with a note naming the split and the counts, and that the other splits' tests are not run by it.
- [x] 13.2 Test: the same file asserts the unit of a change whose split is held runs nothing, is held planned with the split named and the change stays open, that other splits' units run meanwhile, and that when the split is released it resumes and runs.
- [x] 13.3 Test: `tests/pipeline/test_scheduled_e2e_split_failure.py` asserts a failing test of a split is recorded with that split and fixed by one change, holds only runs that execute that split, and that a failure in `rest` never holds another split's unit.
- [x] 13.4 Make the scheduled unit read its split from its change's name and pass it as the one split to the e2e-test session, and name the split in the satisfied note.

## 14. [agent-build-kit] [unit-test] The scratch setup of the live tests is chosen by runtime, and the two build tests lose acp from their names

Needs: tier2-splits-replace-runtime-tags group 10 — builds on the split code, not the runtime names

Done when one helper builds a scratch installation for a named runtime (its `runtimes` entry, the `ABK_RUNTIME` override, its agent home and its start check), the two scratch tests are renamed `test_build_unit.py` and `test_graph_unit.py` with every reference updated, and a test fails if an old name is found anywhere. Estimate: about 250 changed lines.

- [x] 14.1 Test: `tests/test_live_test_names.py` asserts `tests/integration/test_acp_build_unit.py` and `tests/integration/test_graph_acp_unit.py` do not exist, `test_build_unit.py` and `test_graph_unit.py` do, and that no tracked file of the repository (documentation, project configuration, scripts, skills, tests) names either old module, with the changelog's history exempt.
- [x] 14.2 Test: `tests/integration/test_runtime_scratch_setup.py` asserts, with the agent's start check faked, that the helper writes the `runtimes` entry and the override for `acp` from the agent command setting, writes none for `claude_code` and sets its account variables, fails (not skips) naming the setting when `acp` has no command, and gives each runtime parameter exactly one tag.
- [x] 14.3 Rename the two scratch tests with their history, update the imports and lists that name them (the scratch change test, the time-split module list, the agent-runtimes document), and leave the telemetry and init-conventions names as they are.
- [x] 14.4 Add the helper beside the existing agent-home helper, giving the tests the per-runtime parameters, each carrying its one tag, and the per-runtime steps a test calls where a runtime needs one.

## 15. [agent-build-kit] [e2e-test] The build test runs on Claude, and the ACP agent's forbidden-command refusal leaves it for the change that adds the ACP variants

Needs: tier2-splits-replace-runtime-tags group 10 — builds on the split code, not the runtime names
Needs: a-failed-live-test-says-what-its-scratch-tick-did group 4 — the shared tick helper and the failure dump, so a run of these live tests that builds nothing says why

Done when `test_build_unit.py` drives one unit through the real runtime as a parameter for `claude_code` alone, tagged `runtime_claude_code`, the report and run-log scenarios hold on it, and the forbidden-command refusal naming its layer, which is the ACP agent's own, is no longer in that file; the ACP parameter of the file and the file `test_acp_forbidden_command.py` are out of scope of this change and are added later by the separate change `acp-variants-of-the-runtime-tests`. Estimate: about 200 changed lines.

- [x] 15.1 Test (`local_stack`): `tests/integration/test_build_unit.py` builds, reviews and pushes the unit as before for the `claude_code` parameter (one tag, `runtime_claude_code`), asserting the commit order, that the pipeline alone pushed what review approved, the visible progress, the run log's review round and pull request, and the run log's line about the runtime's usage window as a Claude run states it (the text the real run in 15.4 shows).
- [x] 15.2 Test (`local_stack`): the same file asserts for the `claude_code` parameter that `abk report` for the unit has one agent record per agent call in the run log and that its totals equal the ledger with each figure's source named, and that its fixtures request the scratch ledger as the time-split plugin requires.
- [x] 15.3 Test: `tests/integration/test_build_unit.py` collects only items tagged `runtime_claude_code`, each with that one tag, and holds no test of the amend attempt or any other ACP-only step; the forbidden-command test it carried is removed from the file, and its refusal check (the amend attempt is refused with the layer named and the branch not rewritten) is carried by `acp-variants-of-the-runtime-tests`.
- [x] 15.4 Run the Claude parameter of the file once against the real runtime, and correct what the real run shows about the Claude variant's expectations.
- [x] 15.5 Test: a unit test in `tests/test_scratch_app_instructions.py` asserts that the scratch app the build test creates (`scratch_app` in `tests/factories.py`) has an instruction file at its root (`CLAUDE.md`) that tells the build agent to run the tests with `uv run pytest -q` and to lint and format with `uv run pre-commit run --all-files`, names no bare `pytest`, `python -m pytest` or `ruff` command, and that both commands match the `python-uv` profile's `allowed_tools` (read from the profile, not copied), because the headless build session can run only what that list allows and `ruff` is not in the scratch app's dev group.
- [x] 15.6 Add the instruction file to `scratch_app` (`tests/factories.py`) so the tests and implement steps of the build test follow it, and carry the commands from the profile's own settings instead of typing them again where the profile exposes them. This is a fix to the test's scratch app only; the build prompts are not changed here (a separate product change names the profile's runner in the prompts).

## 16. [agent-build-kit] [e2e-test] The graph test runs on Claude, and the ACP agent's session listing leaves it for the change that adds the ACP variants

Needs: tier2-splits-replace-runtime-tags group 10 — builds on the split code, not the runtime names

Done when `test_graph_unit.py` drives the unit to review, rework on a comment and the thread's end at merge as a parameter for `claude_code` alone, tagged `runtime_claude_code`, and holds no ACP-only step; the ACP parameter of the file and the check that the agent lists the build's session for the working directory (`test_acp_session_step.py`) are out of scope of this change and are added later by the separate change `acp-variants-of-the-runtime-tests`. Estimate: about 180 changed lines.

- [x] 16.1 Test: `tests/integration/test_graph_unit.py` collects only items tagged `runtime_claude_code`, each with that one tag, none for `acp`, and calls no ACP-only step (the session listing is not called from it; its helper and `test_acp_session_step.py` are carried by `acp-variants-of-the-runtime-tests`).
- [x] 16.2 Test (`local_stack`): the file builds the unit to review for the `claude_code` parameter (one tag, `runtime_claude_code`) and asserts the branch reached the remote, the pull request was opened, and the thread waits at the review wait, that a tick with nothing new changes nothing, and that the thread of the unit is gone after the merge.
- [x] 16.3 Test (`local_stack`): the same file asserts for the `claude_code` parameter that a review comment resumes the thread into a rework that pushes a second commit without rewriting the first, reads the comment, and answers in the comment's own thread.
- [x] 16.4 Run the Claude parameter against the real runtime once, and correct what the real run shows about how Claude's rework and comment reply differ.

## 17. [agent-build-kit] [e2e-test] The telemetry test runs its trace and metric checks on Claude

Needs: tier2-splits-replace-runtime-tags group 10 — builds on the split code, not the runtime names

Done when `test_telemetry_stack.py` builds the fixture unit with telemetry on for `claude_code`, tagged `runtime_claude_code`, the trace and series checks hold on it, and the check that a dead collector is survived runs on Claude alone with its reason stated; the ACP parameters of the file are out of scope of this change and are added later by the separate change `acp-variants-of-the-runtime-tests`. Estimate: about 190 changed lines.

- [x] 17.1 Test (`local_stack`): `tests/integration/test_telemetry_stack.py` builds the fixture unit once, for the `claude_code` parameter (one tag, `runtime_claude_code`), and asserts the trace is found by the unit id with a tick root, a unit span and a step span, and the duration series carry the repo, tier, outcome and step labels with no unit or change name.
- [x] 17.2 Test (`local_stack`): the same file asserts that with the collector pointed at nothing the tick finishes, the unit is pushed and nothing is written to the stores, tagged `runtime_claude_code` only and carrying a stated reason that a build on a second runtime adds no coverage of the collector, which does not depend on the agent (the ACP variants of the other checks are added later by `acp-variants-of-the-runtime-tests`).
- [x] 17.3 Update the timing-hazard lists that name the file, and run the Claude parameter against the real runtime and the dev stack, correcting what they show.

## 18. [agent-build-kit] [unit-test] A drift test fails an untagged live test that drives an agent, and an ACP scenario with no Claude variant and no reason

Needs: tier2-splits-replace-runtime-tags group 10 — builds on the split code, not the runtime names

Done when a test over the kit's live-stack tests fails when one that starts an agent (through the scratch helper, the agent-home helper or the agent command setting) has no runtime tag, fails when a scenario has an ACP variant and no Claude variant without a stated reason, and the untagged init-conventions test passes it. Estimate: about 250 changed lines.

- [x] 18.1 Test: `tests/test_live_tests_are_tagged.py` collects the live-stack modules and asserts each test that requests an agent fixture, imports the scratch or agent-home helper or reads the agent command setting carries exactly one runtime tag, naming each that does not, and that the init-conventions module, which starts no agent, passes untagged.
- [x] 18.2 Test: the same file asserts a fixture module with an ACP-tagged test whose scenario has no `claude_code` sibling and no entry in the module's reasons table fails naming the scenario, that an entry with an empty reason fails, and that an ACP-only scenario with a stated reason passes.
- [x] 18.3 Test: the same file asserts a scenario that needs two runtimes written as one test with two tags is already refused by the collection check, and the drift test names the pair.
- [x] 18.4 Add the drift test and the module-level reasons table the kit's ACP-only scenarios state their reasons in. The table is empty here: groups 15, 16 and 17 leave no ACP-only scenario in this change, and the forbidden-command refusal and the session listing state their reasons when `acp-variants-of-the-runtime-tests` adds them. On the kit's own modules the drift test then asserts that every test that starts an agent carries exactly one runtime tag; its rule about an ACP variant with no Claude variant and no reason holds trivially until that change adds one. The gap it leaves: it never checks that a Claude test has an ACP sibling, so a Claude-only test passes without one and the missing ACP halves are tracked only by the draft.

## 19. [agent-build-kit] [unit-test] The documents say how the kit's tests are tagged and split and how a split is held

Needs: tier2-splits-replace-runtime-tags group 11 — builds on the split code, not the runtime names

Done when the runtimes and command documents and the three skills describe the kit's tags and its two splits, the `abk e2e-test hold`, `release` and `status` commands, parking and the scheduled changes per split, with a short how-to for holding a split; the settings and `abk e2e-test check` are documented by `tier2-splits-replace-runtime-tags`. Estimate: about 300 changed lines.

- [x] 19.1 Test: `tests/test_docs_e2e_holds.py` asserts the command document has an entry for each of `abk e2e-test hold`, `release` and `status`, the runtimes document names the kit's tag rule and has a section on holding a split, and each of the three skills names the commands.
- [x] 19.2 Document the kit's tag rule and its splits, the parking and the scheduled changes per split in the runtimes document, the `abk e2e-test hold`, `release` and `status` commands and their refusals in the command document, and the architecture notes on the gate and the record.
- [x] 19.3 Add a short how-to to the runtimes document: hold a split (it has no deadline: only `release` ends a hand-set hold), see what waits on it, release it, and what the configuration winning means when the two disagree.
- [x] 19.4 Update the configuration, authoring and pipeline skills for the commands and the waiting reason, and add a changelog entry under the unreleased heading.
