## Context

Code at agent-build-kit `origin/main` (a8973afc); lines are in that tree.

- **Join legality.** `check_joins` (`pipeline/joins.py:52`) calls `_check_groups(involved, catalog, refuse)` (`:172`, defined `:213-229`): it refuses a group with
  a `flag`, `Separate:` or `Independent:`. Earlier in the loop, `_needs_stack` (`:204-206`) requires both sides to need the stack or neither
  (`:109`, `:144`), so two e2e units can join. `TaskGroup.tier` (`work_graph.py:197-221`) is the tier; there is no e2e property.
- **The plan check.** `_check_groups` of the planner (`planner.py:477-545`) checks repo, project, split and double claims; `check_flagged_groups`
  (`:562-565`, called at `:226`) runs `_check_acceptance` (`:568-604`) and `_check_independent` (`:607-640`). Each raises `PlannerError`, which the
  planning loop re-asks within its attempt budget. Nothing there refuses a unit that holds several e2e groups.
- **The planner prompt** (`PROMPT`, `planner.py:726-860`): the grouping bullet (`:755-760`), the `[acceptance]` bullet (`:793-797`), the `Independent:`
  bullet (`:798-803`) and the join rules (`:828-836`: "same repo and compatible kinds ... `e2e-test` only with `e2e-test`"; "no group involved is flagged
  `[acceptance]`, `[contract]` or `[narrow]`, or has a `Separate:` or `Independent:` line").
- **What the build does with an e2e unit.** `tests`/`stub_checks`/`implement` (`graph/nodes.py:1301-1473`), then `checks` (`:1475`), review, and
  `e2e` after review (`after_review` -> `Node.E2E`, `:2636-2644`). A failing `e2e` stores feedback with source `FeedbackSource.E2E` and stops
  (`:2057-2067`); a requeue reaches `rework` (`:1748`), where `failed_check` (`:1757`) selects `CHECKS_PROMPT` with `advice(feedback, source)`
  (`stack_runner.py:189-205`). `after_rework` goes to `CHECKS` (`:2646`).
- **The fix machinery for broken tests.** `ensure_fix`/`preview`/`_write_change` (`untouched_failures.py:75-113, 150-236`) and `wait_on_fix`
  (`flakes.py:125-140`) under a file lock, naming by `fix_change_name` (`flakes.py:109-118`: prefix, slug, a hash when over 70 chars), `open_fix_change`
  and `next_fix_name` (`:155-180`: an open change is reused; an archived attempt makes a numbered successor with a restating spec),
  `add_needs_to_unit` (`:183-209`, a `Needs: <fix> group 1 — <reason>` line in every group of every member), a `FailureRecord` jsonl in the state
  directory (`failure_record.py`), and the unit side: `park_for_fix` (`nodes.py:1538-1543`: `hold(..., cause=GATED)` and
  `set_gated_requeue(RESUME)`). The wiring is `build_on_preexisting` (`wiring.py:1540-1572`). A parked unit is requeued when its parents land:
  `_requeue_ended_wait` (`cli/pipeline.py:2062-2080`) with `_wait_end_mode` (`:2049-2059`: resume, or rework when the stored feedback is from a check).
  Those fix changes are `Priority: 1` and `[unit-test]` for flakes, `[e2e-test]` for failing tests.
- **The skill and what it can do.** `abk-authoring` is text a person or a proposing track reads before it writes `tasks.md`. It exists before any
  code does, and it cannot see a defect that shows up only when a live test runs. It tells authors what an e2e group may hold; what happens when a
  defect is discovered during a run is decided by the guard (C) and the prompts and pipeline (D), not by the skill.

## Decisions

### (A) An e2e-test group is never joined and needs no `Separate:`

- **Rule.** A group whose tier is `e2e-test` always has a unit with no other group. It is read from the heading (tier), no model call.
- **`joins.py`.** `_check_groups` refuses any involved group whose `tier` is `TestTier.E2E_TEST`: "`<change>` group `<n>` is `[e2e-test]`, which always has a
  unit of its own". It sits before the flag test so the message is the e2e one for an `[e2e-test] [acceptance]` group too. This also covers a join
  `onto` a unit that holds an e2e group (its members are in `involved`). `_needs_stack` stays: it still keeps unit-test groups off e2e units.
- **The plan check.** `check_flagged_groups` gains `_check_e2e_alone(units, groups)`: any unit holding an e2e group and another group is a
  `PlannerError` naming the unit and groups, re-asked within the attempt budget, as `_check_acceptance` is. The unit-level check is needed because the
  grouping (not only the joining) can put two e2e groups in one planned unit.
- **The prompt.** The grouping bullet (`:755`) adds "except `[e2e-test]` groups: each is a unit of its own, however small"; a new bullet next to the
  `[acceptance]` one says an `[e2e-test]` group, flagged or not, stands alone, never combined with another group, and that its unit depends on the
  groups before it as the chain gives; the join rules (`:828-836`) drop "`e2e-test` only with `e2e-test`" in favour of "an `e2e-test` group is
  never joined, not even with another `e2e-test` unit" and add `[e2e-test]` to the list of groups never involved.
- **`abk tags`.** A `Separate:` line in an e2e group is accepted with a warning that it is redundant (a warning in `_tag_warnings`,
  `cli/pipeline.py:5380`, which both `abk tags` and `abk check` print).
- **Already stored joined units.** Nothing rewrites a stored unit by itself. A **started** unit (a branch, a pushed commit, a pull request or an
  approval) keeps its groups per the merged rule "a started unit keeps its groups" and is not split, so e.g. a started unit of groups 1,2,3 finishes as
  one. An **unstarted** one is re-planned the next time its change is planned (`abk plan <change>`): the new plan is checked as any plan, so it gives
  each group a unit; the old unit the plan no longer contains becomes `unplanned`. A test over stored fixtures pins this (tasks group 1). The
  groups of another change that an unstarted unit carries are replanned with their own change; they are not touched here.
- **Sizing.** An e2e unit's estimate is its group's; the minimum-size grouping does not apply to it; one group over the ceiling is reported as needing its
  tasks split, as for any group. Cost accepted: more, smaller e2e PRs, each still serialized on the stack.

### (B) `abk tags` / `abk check` warn on product paths in an e2e group

- **Reading paths.** For each task line of an e2e group (a checkbox line numbered within the group), take backticked tokens; keep those that look like
  repo paths: contain `/`, or end in `.<letters/digits>`; have no space; do not start with `-`, `http`, `$` or contain `=`, `(`, `<`, `*`; drop a trailing
  `:<digits>` or `::<test id>` and a trailing `/`. Limits, stated in the docs: only backticked tokens are seen, so "fix the retry in the client" and an
  unquoted path pass; a path named only as context ("the test calls `src/client.py`") warns although nothing there is edited, which is why this is a
  warning; a symbol (`retry()`) is not a path; a glob is skipped.
- **Allowed.** A path is fine when it is: a test path (the repo's profile for the path's project, `profiles.for_path(...).is_test_path`, as
  `nodes.outside_note` and `gate.py:90` use it, which covers the e2e test directories); a doc path (`profiles/base.py:286 is_doc_path`); the repo's
  `changelog` file (`config.py:1165`); a `Support:` path of the group; or a path under `scripts/` that is named on a task line that also names a test
  path (the test uses it). Reading the test's content to see whether it uses a script is not attempted: the planning repo has no code.
- **Output.** One warning per path and group, `file:line: warning: group <n>: task <n.m> names <path>, which is not a test path, a doc, the changelog or
  declared support; an [e2e-test] group holds tests, and a product defect a live test finds is fixed by a [unit-test] change the pipeline files`.
  Not an error: the tasks may be right (a support file) and the guard (C) is the check that cannot be talked past.
- **The allowance: `Support:`, not an `abk.yaml` list, not a `Touches:`.** `Support: `scripts/seed.sh`, `compose.e2e.yml` — <reason>` inside the
  group, parsed beside `Separate:` and `Independent:` (`work_graph.py:178-182`), reason required, only in an e2e group. Chosen because (1) it is
  per group and reviewed with the plan, where the need is known; (2) the build reads it from the plan (the planning repo's `tasks.md`, which the
  builder cannot edit: "the change's files are read-only for you"), so a builder cannot allow itself a file; (3) it needs no config schema, no
  `abk.yaml` edit and no migration; (4) one shared function (the group's declared support plus the scripts/ rule) feeds both the warning and the guard.
  An `abk.yaml` list would be installation-wide (a path allowed for every e2e group forever) and a `Touches:` line would not carry a reason. The
  costlier alternative, with no allowance at all (every non-test file goes to a `[unit-test]` group), is kept as the rule for anything that is more than
  a tiny file.
  The scripts/ co-naming rule applies to the warning only; for the guard a script must be declared, because the guard has no task text to read a
  test's use of it from. The authoring text therefore says: declare a script with `Support:`.

### (C) The build-time guard

- **Where.** At the top of `checks` (`nodes.py:1475`), after the environment test and before `run_unit_test`. Every path to review passes through `checks`
  (`after_implement`, `after_rework`, `after_fix_checks`, `after_prepare`'s default), so the guard also sees a rework that edits product code, a
  resume and a restack. It runs after the implementation/tests commits, as asked, and before a unit-test run is spent on a diff that will be refused.
  Alternatives rejected: in `implement` (not reached by a rework), in `push` (the check would be late: review and e2e would have been spent).
- **What.** If `self.unit.tier` is `e2e-test`: `shell.changed_files(tree, self.ref(state))` (`shell.py:48`, `git diff --name-only base...HEAD`), then
  every file that is not a test path of its project's profile, a doc path, the repo's changelog file, or a `Support:` path of one of the unit's groups
  is "product". A unit that holds an e2e group holds only it (A), so "the unit's groups" is that group; stored joined units are checked against all of
  theirs.
- **Stop.** Like the pair-count stop (`nodes.py:1458`): `self.stop("the e2e-test unit changes product code: <files>")`, and the same text kept as feedback
  with a new `FeedbackSource` member (`scope`), so a requeue goes to `rework` (`failed_check` includes it) with the text. The text names the files and
  says: these are product code, not tests or test support; restore them to the base in this unit (`git restore --source=<base> -- <files>`
  style: the builder knows how), keep the diff to tests and test support; if they fixed a real defect report it as a `product-defect` block (D) so the
  pipeline files a `[unit-test]` change that reproduces it and fixes it, and this group waits on it. A person's `Support:` line is the way out for a
  support file.
- **No model, no retry timer.** The stop is a stop; a person or an event requeues it.
- **Acceptance groups** that add a tiny non-test file (a script, a compose override) declare it with `Support:` as above.

### (D) A product defect gets a fix unit of its own

The earlier plan, "the builder stops and reports BLOCKED", is replaced: the person wants the pipeline to create the product-fix unit itself, as it
does for broken tests.

- **Where the defect is discovered.** Only in the e2e step: the builder cannot run live tests. So the entry point is the rework that follows a
  failing e2e step (`failed_check` with source `E2E`) or the guard's stop (source `scope`). The first build of an e2e group writes tests; it finds nothing.
- **The prompt.** In `ChecksTemplate.advice` (`stack_runner.py:189-205`) the E2E branch gains a paragraph, and the first-build prompts (`TESTS_PROMPT`,
  `IMPLEMENTATION_PROMPT`) get a short scope note when the unit is `e2e-test` (via `told()`, as the outside-commits note is added): the unit holds tests
  and test support only. The paragraph: decide first whether the fault is in the test or in its support (a wrong assertion, fixture, helper, selector,
  expectation, timing): fix those in place, as today. If the product under test is wrong (the test asserts what the specification requires and the
  product does not do it) do not edit product code; finish your account with a fenced block marked `product-defect` holding JSON:
  `{"test": "<the failing e2e test id>", "files": ["<product file>", ...], "reproduction": "<smallest steps or request, expected vs actual>",
  "sketch": "<optional: a failing unit test that reproduces it>", "repo": "<optional>"}`.
- **Reading it.** A new pure function reads the last `product-defect` block of the account (a pydantic model; `test` and `reproduction` required,
  `files` non-empty) with no model call. Checks, all deterministic: JSON valid; `test` is one the saved failure feedback names (an id that appears in
  the feedback text); at least one file is product by the same classifier as (C) (a report whose files are all tests or docs is the test's fault: stop
  and say fix it in place); `repo` declared. Any failure stops the unit with the reason; nothing is filed. No block means an ordinary rework: a defect
  in the unit's own test or helper is fixed in place on this unit, as today.
- **Filing.** `ensure_product_fix(inst, defect, unit)` beside `untouched_failures.ensure_fix`: under `state_dir/product-defects.lock`,
  `open_fix_change(inst, test, "fix-product-defect")` reuses an open change (log `exists: <change>`), else `next_fix_name` and `_write_change`
  (log `would write` then `wrote`), exactly as the others, so **two units meeting one defect share one fix** (the key is the test id). The record is
  `product-defects.jsonl` (a `FailureRecord[ProductDefect]`: test, files, reproduction, sketch, unit, at, change). Written without a model:
  - `proposal.md`: why (the test, the unit, the reproduction, the sketch, the files reported), history of units that met it;
  - `design.md`: the question "is the reported file the fault? decide from the reproduction";
  - `tasks.md`: `Acceptance: none — the e2e-test unit that found it is the check.`, `## 1. [<repo>] [unit-test] Reproduce <test> with a unit test, then fix it`,
    `Priority: <the e2e unit's priority>`, a "Done when" sentence, `1.1 Test:` a unit test that reproduces the reported behaviour (the reproduction text and sketch
    carried in the task), `1.2` make it pass, with the reported files named as where the e2e unit's builder believes the fault is;
  - `specs/product-defects/spec.md`: one requirement ("`<test>` passes against the fixed product") ADDED, MODIFIED for a successor.
- **Waiting.** `add_needs_to_unit` gives every group of the unit a `Needs:` on the fix (reason "product defect found by `<test>`"); a unit of the fix change
  itself waits on nothing. The rework then clears the stored feedback (so `_wait_end_mode` resumes instead of reworking) and returns
  `park_for_fix(note)`: held, gated, `RESUME` requeue, the unit shown by `abk status` as `failed, waiting on <fix unit>`. When the fix unit enters
  review `_requeue_ended_wait` requeues it (same-repo `Needs:` starts the dependent on the parent's branch once the parent is in review) and its
  e2e step runs again. The wiring is `build_on_product_defect` beside `build_on_preexisting` (`wiring.py:1540`), a runner hook as `on_preexisting`.
- **Priority.** Inherited from the unit at filing; later promotion rules already raise a prerequisite to its dependent's priority.
- **A second report after the fix.** The same test fails again: the change is still open (in review) or archived, so the successor path applies; the
  rework limits (`out_of_rounds`) bound the loop and no recurring timer retries (`feedback_no_auto_retry_stopped_jobs`).
- **Guard and (D) together.** The guard's stop hands the builder the same path: restore the product files, report the defect. The pipeline files
  the fix; the guard sees the restored diff on the next `checks`.
- **Limits.** The builder's report is a model's word: the checks above catch malformed and test-only reports, not a wrong diagnosis; the fix unit's
  own reviewer judges the reproduction. Two different tests on one defect get two changes. A cross-repo defect uses `repo` and the ordinary
  cross-repo `Needs:` (waits for a merge).

### (E) The skill and the docs

- **Skill source** (`src/agent_build_kit/skills/abk-authoring/SKILL.md`): a paragraph under `Flags`/`Separate:` saying an `[e2e-test]` group (1) always has
  a unit of its own, flagged or not, and needs no `Separate:`; (2) may hold test files, test fixtures and helpers (under test paths), docs, the
  changelog and files declared with `Support:`; (3) does not hold product code: "do not put product fixes in an e2e group; the pipeline makes the fix
  unit when a live test finds one"; and an author who already knows of the defect writes a `[unit-test]` group earlier in the change (or another
  change the e2e group `Needs:`). The `Separate:` paragraph's list of never-joined groups adds `[e2e-test]`; the version of the skill is bumped.
- **Docs**: `docs/architecture.md` (the join rules, `:196-210`, and the build/e2e paragraphs), `docs/cli.md` (`abk tags`, `:364-376`), `docs/unit-graph.md`
  (the `checks` guard row) and the `abk-pipeline` skill (a product-defect paragraph beside the pre-existing one at `:274`).
- **Honest limits of the skill.** It guides whoever writes `tasks.md` (a person, or a proposing track), before any code exists; the pipeline does not
  consult it at run time. It cannot make a builder keep to an e2e group's scope, and it cannot know about a defect nobody has met yet. What acts at run
  time when a defect is found is the guard (C), the prompts and the pipeline path (D); the path warning (B) is the bridge: it reads the same
  `tasks.md` the skill guides and complains when the text leaves the scope.

## Relation to `a-test-only-group-commits-no-pair`

That change defines a test-only group as `[e2e-test]` + `[acceptance]` and builds it as one `test:` commit. After this change every `[e2e-test]` group is
test-only in content, so a plain `[e2e-test]` group in a stubbed build would meet the pair-count stop that change removes for acceptance groups. This
change does not touch that rule. Follow-up (open, not done here): extend "test-only" to every `[e2e-test]` group, or require a plain e2e group to be
flagged; decide once both have landed.

## Risks

- **More e2e units.** Each is its own PR and its own stack lock turn; accepted for clearer failures and reverts.
- **A false positive in (B)** is a warning. **A false positive in (C)** stops a unit; the message names the files and `Support:` is the way out.
- **A product-fix change with a wrong reproduction.** Reviewed as a `[unit-test]` unit with a test-first requirement.
- **Planning-repo writes at run time.** Filing writes a change directory and `Needs:` lines in the planning repo, as the other fix machinery does.
