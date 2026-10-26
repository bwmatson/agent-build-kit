# Tasks

Acceptance: none — every behaviour is proved by a unit-test over temporary planning and git repositories, fake agents, fake profiles and a fake runner, as the sibling changes' are; nothing a consumer drives is built.

Priority: 2

## 1. [agent-build-kit] [unit-test] An e2e-test group is never joined and needs no `Separate:`

Priority: 2

Done when a join that carries or joins an `[e2e-test]` group (flagged or not) is refused, a plan that gives one unit an e2e group and another group is refused and re-asked, the planner prompt says so in its grouping, flag and join rules, `abk tags` calls a `Separate:` line on an e2e group redundant, and a stored joined unit is left alone when started and split by the next plan when not. Estimate: about 320 changed lines.

- [x] 1.1 Test: in `tests/pipeline/test_joins_e2e_alone.py`, over fake stores, a join of a plain `[e2e-test]` group onto an unstarted e2e unit of the same repo, project and split is refused naming the group and saying it always has a unit of its own; so is a unit-onto-unit join where either holds an e2e group, and an `[e2e-test] [acceptance]` group is refused with the e2e message; a `[unit-test]` pair still joins.
- [x] 1.2 Test: in `tests/pipeline/test_planner_e2e_alone.py`, a plan that puts consecutive plain e2e groups in one unit, or an e2e group with a unit-test group, raises the planner error naming the unit and groups and is asked again within the attempt budget; one unit per group is accepted, group n+1 depending on group n, and a lone e2e group over the ceiling is reported as needing its tasks split.
- [x] 1.3 Test: in `tests/pipeline/test_planner_prompt_e2e_alone.py`, the prompt says an `[e2e-test]` group (flagged or not) is a unit of its own and that the minimum-size grouping does not apply to it, no longer says `e2e-test` joins only with `e2e-test`, and lists `[e2e-test]` among the groups no join involves.
- [x] 1.4 Test: in `tests/cli/test_tags_separate_e2e.py`, `abk tags` and `abk check` print a warning, with the file and line, for a `Separate:` line in an `[e2e-test]` group, print nothing for one in a `[unit-test]` group, and exit as before.
- [x] 1.5 Test: in `tests/pipeline/test_replan_stored_e2e_units.py`, over the stored fixtures of two unstarted units each holding e2e groups 1, 2 and 3 of one change, planning the change again with a planner that returns a unit per group gives three units and makes the old ones `unplanned`; a started unit holding the same groups keeps them and is reported as kept; nothing rewrites a stored unit with no replan.
- [x] 1.6 Make the join check, the plan check, the planner prompt and the `Separate:` warning follow the tests.

## 2. [agent-build-kit] [unit-test] `abk tags` and `abk check` warn of product paths in an e2e-test group, and `Support:` declares support

Priority: 2

Done when a `Support: <paths> — <reason>` line is read in an e2e group (reason required, refused elsewhere), and a task line of an e2e group that names in backticks a path that is not a test path, a doc, the changelog, declared support or a script co-named with a test path draws one warning per path and group, with limits as the documents state. Estimate: about 300 changed lines.

- [x] 2.1 Test: in `tests/pipeline/test_support_line.py`, a `Support:` line with backticked paths and a reason in an `[e2e-test]` group is read as that group's support (a trailing `/` covers a directory); without a reason, or in a `[unit-test]` or `[integration-test]` group, `validate_tasks` returns an error at the line; a second line adds paths.
- [x] 2.2 Test: in `tests/pipeline/test_e2e_group_paths.py`, the reader of task paths takes backticked tokens with a `/` or a file extension, drops `:<line>` and `::<test id>` and a trailing `/`, and skips URLs, flags, assignments, globs and symbols; and the classifier judges test paths by the repo's profile for the path's project, docs by `is_doc_path`, the changelog by the repo's setting, declared support, and a `scripts/` path on a line that also names a test path.
- [x] 2.3 Test: in `tests/cli/test_tags_e2e_product_paths.py`, `abk tags` and `abk check` warn `group 1: task 1.2 names src/client/retry.py, which is not a test path, a doc, the changelog or declared support` for that path in an e2e group, print nothing for `tests/e2e/test_route.py`, `docs/cli.md`, `CHANGELOG.md`, a `Support:` path, or a script on a line with a test path, warn for a script on a line without one, print nothing for the same text in a `[unit-test]` group, and do not change the exit code.
- [x] 2.4 Parse the `Support:` line and print the warnings through the tag-warnings function both commands use.

## 3. [agent-build-kit] [unit-test] An e2e-test unit whose diff changes product code is stopped

Priority: 2

Done when the checks step of an `[e2e-test]` unit lists the files its branch changes against its base and stops the unit, naming them, when any is not a test path, a doc, the changelog or a `Support:` path of its groups read from the plan, saving feedback of its own that tells the builder to restore them and report a product defect; a unit of another tier is not checked, and a rework that restores the files goes on. Estimate: about 330 changed lines.

- [x] 3.1 Test: in `tests/graph/test_e2e_scope_guard.py`, with a fake runner over a temporary repository, an e2e unit whose branch changes `tests/e2e/test_route.py` and `src/app/route.py` is stopped at `checks` before any unit-test run, the reason names `src/app/route.py` and not the test, and the saved feedback has the scope source and says to restore the files, keep the diff to tests and test support, and report the defect for the pipeline to file.
- [x] 3.2 Test: the same file asserts a diff of `tests/e2e/conftest.py`, `docs/e2e.md` and `CHANGELOG.md` goes on; a changed file declared by the plan's `Support:` line goes on while a `Support:` line added on the branch to the change's own `tasks.md` does not allow anything; a `[unit-test]` unit changing `src/app/route.py` is not checked; and a unit stopped for `src/app/route.py` and requeued reaches `rework` with the feedback, and goes on to the unit-test run once the file is restored.
- [x] 3.3 Test: the same file asserts the guard also runs on a resume and after a rework commit that adds a product file, and that a stored unit holding two e2e groups is judged against the support of both.
- [x] 3.4 Add the feedback source, the classifier shared with the path warning, and the guard at the top of `checks`.

## 4. [agent-build-kit] [unit-test] The builder reports a product defect in a structured block, read without a model

Priority: 2

Done when the e2e rework prompt tells the builder to fix a test or support fault in place and to report a product fault, editing no product code, as a `product-defect` block; the first-build prompts of an e2e unit say it holds tests and test support only; and a deterministic reader turns an account into a defect, nothing, or a refusal with a reason. Estimate: about 340 changed lines.

- [x] 4.1 Test: in `tests/pipeline/test_product_defect_report.py`, the reader returns a defect from the last fenced `product-defect` JSON block of an account (test, files, reproduction, optional sketch and repo); returns nothing when there is no block; and refuses, with a reason each, a block that is not valid JSON, lacks `test` or `reproduction`, has empty `files`, names a test the saved failure does not mention, names an undeclared repo, or lists only test and doc paths (which it calls the test's fault).
- [x] 4.2 Test: in `tests/graph/test_e2e_rework_prompt.py`, the rework prompt for feedback with the e2e source, and for the scope source, contains the instruction to fix a test or helper fault in place, not to edit product code for a product fault, and the block's fields; the same prompt for a unit-test failure is as before; the first-build prompts of an `[e2e-test]` unit carry the scope note and those of a `[unit-test]` unit do not.
- [x] 4.3 Make the prompt text, the scope note and the reader.

## 5. [agent-build-kit] [unit-test] A reported product defect gets one fix change, and the e2e-test unit waits on it

Priority: 2

Done when a valid report makes the pipeline write one `fix-product-defect-<test>` change with a single `[unit-test]` group that reproduces the defect and then fixes it, at the e2e unit's priority, reusing an open change for the same test, gives the unit's groups a `Needs:` on it, clears the unit's saved failure, parks it failed-waiting on the fix, and requeues it when the fix is in review; a refusal stops the unit; no block is an ordinary rework. Estimate: about 480 changed lines.

- [x] 5.1 Test: in `tests/pipeline/test_product_defect_fix.py`, over a temporary planning repo, a report for `tests/e2e/test_route.py::test_stream` from a unit of priority 2 writes proposal, design, spec and a `tasks.md` whose single group is `[<repo>] [unit-test]` titled to reproduce then fix, `Priority: 2`, with the reproduction and the sketch in its text, no model called, and logs `would write:` then `wrote:`; the record file gains an entry.
- [x] 5.2 Test: the same file asserts a second report for the same test from another unit writes nothing, logs `exists: <change>`, and gives the second unit its `Needs:` too; a report after the first change was merged and archived writes a numbered successor whose spec is MODIFIED; a name over the limit is cut with a hash; a unit of the fix change itself gets no `Needs:`; and two reports at once under the lock write one change.
- [x] 5.3 Test: in `tests/graph/test_e2e_rework_product_defect.py`, with a fake agent whose account holds a valid block, a rework of an e2e unit with the e2e feedback files the change, adds the `Needs:` line to each group, clears the stored feedback, and returns a held, gated unit with a resume requeue and no `fix:` commit of product code; with no block it commits an ordinary `fix:` and goes to `checks`; with a refused block it stops with the reason and files nothing.
- [x] 5.4 Test: in `tests/cli/test_product_defect_requeue.py`, a unit parked on a product-defect fix shows as failed, waiting on the fix unit in `abk status`, and is requeued once with the reason `its wait ended` when the fix unit is in review, resuming (not reworking) because its feedback is empty; it is not requeued while the fix unit is planned; and `abk tick --dry-run` prints `exists:` or `would write:` for a recorded defect and writes nothing.
- [x] 5.5 Test: in `tests/pipeline/test_product_defect_priority.py`, two units of priority 2 and 1 meeting one defect share the change written at the first one's priority, and the planner's priority-edge promotion raises the fix to the more urgent dependent as for any prerequisite.
- [x] 5.6 Add the record, the change writer, the runner hook beside the pre-existing one, and the rework step that reads the report and parks the unit.

## 6. [agent-build-kit] [unit-test] The skill source, the documents and the changelog say what an e2e-test group holds

Priority: 2

Done when the `abk-authoring` skill source and the documents say that an e2e group has a unit of its own, what it may hold, that product fixes go elsewhere, that the pipeline files the fix change when a live test finds a defect, how to declare support, and what the path warning cannot see; and the changelog has one bullet. Estimate: about 200 changed lines.

- [x] 6.1 Test: in `tests/docs/test_e2e_group_scope_documented.py`, the `abk-authoring` skill names the stand-alone unit (and that `Separate:` is not needed), the contents list, `Support:`, "do not put product fixes in an e2e group", the `fix-product-defect` change the pipeline makes and the `[unit-test]` group an author who knows of the defect writes first, and lists `[e2e-test]` among never-joined groups with a bumped version; `docs/architecture.md` names the join rule, the checks guard and the product-defect path; `docs/cli.md`'s `abk tags` section names the product-path warning, its backtick-only reading and its false positives; `docs/unit-graph.md` shows the guard; the `abk-pipeline` skill has a paragraph beside the pre-existing one; and `CHANGELOG.md` has the bullet once under `## Unreleased`.
- [x] 6.2 Update the skill source and the documents named above, and add one changelog bullet under `## Unreleased` as the repository's changelog section says: written for the person, one bullet, a two-space continuation, no unit names or numbers.
