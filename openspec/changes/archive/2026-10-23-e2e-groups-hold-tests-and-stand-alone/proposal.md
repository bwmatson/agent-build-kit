## Why

Code at agent-build-kit `origin/main` (a8973afc).

**Joins.** A group flagged `[acceptance]`, `[contract]` or `[narrow]` is never joined (`pipeline/joins.py:213-229`, `_check_groups`, which refuses on
`group.flag`; the planner prompt says the same at `pipeline/planner.py:793-797` and `835-836`; `_check_acceptance` at `planner.py:568-604` refuses a plan
that puts the acceptance group with other work). A plain `[e2e-test]` group has no flag, so the planner may group it with its neighbours
(`planner.py:755-760`, "Group consecutive task groups in the same repo together") and join it with other e2e-test work (`planner.py:828-829`: "`e2e-test`
only with `e2e-test`"; `joins.py:204-206`, `_needs_stack`, pairs e2e with e2e). The unit store shows it:
`consumer-intake-live-tests-run-on-the-current-gateway/1` and `/3` each hold groups 1, 2 and 3. An e2e unit holds the stack lock, runs against the live
gateway and is the unit most likely to be rerun; making it carry three groups makes a failure in one group cost the other two and makes a
PR harder to read and revert.

**Product code in an e2e group.** Nothing says what an e2e group may change. Its job is to prove behaviour against the real stack, and the builder
cannot run the live tests (`ChecksTemplate.advice`, `stack_runner.py:189-205`: "you cannot rerun the live tests"), so when the e2e step fails (`graph/nodes.py:1990-2067`, feedback
source `E2E`) the rework prompt (`CHECKS_PROMPT`, `stack_runner.py:348-374`) tells the builder to "fix every failure", which includes
editing product code inside a unit that is reviewed as tests. A product fix there is untested by a unit test that reproduces it, is carried by a unit
the reviewer is told is an e2e group, and is hard to find later.

**The pipeline already knows how to hand a defect to its own fix unit.** A test that fails on the base is recorded and gets one `fix-failing-<test>`
change written without a model (`pipeline/untouched_failures.py:75-113`, `pipeline/flakes.py:109-160`); the unit gets a `Needs:` line on it
(`flakes.py:add_needs_to_unit`), is parked failed-waiting (`graph/nodes.py:1538-1543`, `park_for_fix`) and is requeued with no person when the fix is in
review (`cli/pipeline.py:2046-2080`, `_requeue_ended_wait`, reason "its wait ended"); that is what left `asr-streaming-service/9` waiting on
`consumer-intake-live-tests-run-on-the-current-gateway/3` and requeued it. A product defect found by a live test is the same shape and can use the same
machinery.

## What Changes

- **(A) An `[e2e-test]` group is never joined**, flagged or not, and needs no `Separate:` line. The join check, the planner's plan check and the
  planner prompt say so; `abk tags` calls a `Separate:` line on such a group redundant. An already stored joined unit: a started one keeps its groups
  (the merged rule "a started unit keeps its groups"); an unstarted one is re-planned the next time its change is planned and is split by the new plan.
- **(B) `abk tags` / `abk check` warn** when a task of an `[e2e-test]` group names (in backticks) a path that is not a test path, a doc, the changelog
  or declared support. A `Support: <paths> — <reason>` line in an e2e group declares the rare support file (a script, a compose override).
- **(C) A build-time guard** in `checks`: an e2e-test unit whose diff against its base changes any other file is stopped, with feedback that names the
  files, tells the builder to restore them and to report the defect through (D).
- **(D) A product defect gets its own fix unit.** The e2e rework prompt tells the builder to fix a test or helper fault in place and, for a product
  fault, to edit no product code and report a structured `product-defect` block (test id, product files, minimal reproduction, optional failing-unit-test
  sketch). The pipeline reads it without a model, writes one `fix-product-defect-<test>` change (a `[unit-test]` group "reproduce with a unit test,
  then fix", reproduction in its text, the e2e unit's priority; once per test however many units meet it), gives the e2e unit's groups a `Needs:` on
  it, parks the unit failed-waiting, and requeues it when the fix is in review.
- **(E) The `abk-authoring` skill source and `docs/`** say what an e2e group may hold and that the pipeline files the fix.

## Impact

Plans of changes with consecutive plain e2e groups get one unit per group (more, smaller PRs, each serialized on the stack as before). Units already
started are untouched. A changed e2e unit that edits product code is stopped once with a clear message instead of reaching review. No new setting, no
change to `abk.yaml`.

## Not in this change

- **Follow-up: `a-test-only-group-commits-no-pair`.** Its "test-only" definition is `[e2e-test]` plus `[acceptance]`. Under this change a plain
  `[e2e-test]` group is also test-only in content (tests and support, no implementation), and in a stubbed build it would meet the same pair-count stop.
  This change does not alter that rule; extending the definition to every `[e2e-test]` group is a follow-up to be decided after both land.
- A defect whose fix belongs in another repo than the unit's: the report may name `repo`, but fixes across repos are not given any ordering beyond the
  existing cross-repo `Needs:` rule.
- Two different tests that fail on one defect each get their own fix change (the key is the test id); the second's reproduction finds the product
  already fixed and its unit is satisfied.
