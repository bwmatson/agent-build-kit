# Tasks

Acceptance: none — every behaviour here is a configuration rule, a pure decision over recorded facts, a prompt and a parsed reply, or a state file, and each is proved by a tier-1 test over fake units, fake replies and temporary directories; nothing a consumer drives is built beyond what those tests drive, and nothing acts on the verdict yet.

Priority: 1

## 1. [agent-build-kit] [unit-test] The `review` section, the protected paths and the classes

Done when abk.yaml accepts the `review` section and each repo's `review` block with the keys and defaults the spec names, the framework's protected defaults are a tested list, a path is protected by the right union of lists, and a unit's class is found from its changed paths, and a unit of the `integration-test` kind is classed as a `unit-test` unit. Estimate: about 410 changed lines.

Needs: test-kinds-are-unit-test-and-e2e-test group 23 — the test kinds are renamed first, so the class of an unmatched unit is `<repo>/<unit-test|e2e-test>`

Needs: integration-test-kind-is-a-label group 1 — the test below builds a unit of the `integration-test` kind, which exists only after that group

- [x] 1.1 Test: in `tests/config/test_review_config.py`, a workspace with no `review` section loads with the defaults the spec names, each key loads when set, an unknown key, a rate outside 0 to 1 and a sample count below 1 each fail naming the key, and a repo's block holds only `protected_paths`.
- [x] 1.2 Test: in `tests/pipeline/test_review_paths.py`, the framework's defaults protect a migration, a CI definition, a container definition, a secrets file and a CODEOWNERS file and do not protect an ordinary source file; the workspace's list and a repo's list are added, a repo's list never narrows the workspace's and does not apply to another repo, and `protected_defaults: false` leaves only the lists.
- [x] 1.3 Test: in `tests/pipeline/test_review_classes.py`, a unit whose every changed path matches a class belongs to it, one with a path that matches none belongs to `<repo>/<kind>`, the first listed class wins, a unit with no changed path belongs to its repo-and-kind class, a unit of the `integration-test` kind with the same paths belongs to `<repo>/unit-test` and no class is ever named `<repo>/integration-test`, and a class name with a slash is refused when the configuration loads.
- [x] 1.4 Add the `review` section and the per-repo block to `config.py`, the defaults list and the path check to a new module under `pipeline/` beside the path matcher, and the class lookup.

## 2. [agent-build-kit] [unit-test] `abk doctor` checks the review section and no agent can write it

Done when `abk doctor` checks the `review` section, and a build agent and a track are refused a write to abk.yaml. Estimate: about 300 changed lines.

- [x] 2.1 Test: in `tests/hooks/test_policy_review_policy_fence.py`, the policy hook denies a build agent a write to the planning repo's abk.yaml and abk.local.yaml by a file write, by a shell redirect and by an editor command, denies a track's run the same, and still allows a write inside the change's own folder. The test names the routes the policy covers and does not claim all routes.
- [ ] 2.1a Test: in `tests/pipeline/test_config_unchanged_by_run.py`, a build run and a track run that change abk.yaml or abk.local.yaml by any route (a fake agent that writes the file with a program the command policy does not name) fail with the file named and the difference shown, a run that changes neither passes with no output, a person's edit during the run fails the same way with a message that says the file changed during the run, and the pipeline's own writes (the units store, the state directory) do not trip it.
- [ ] 2.1b Add the check: read abk.yaml and abk.local.yaml (each may be absent) before a build or track run starts and compare them after it ends, in the code that runs the agent for both the build and the tracks, so it holds on every runtime. Do not restore the file. Add a test under `tests/runtimes/` that starts an ACP session with a `ToolPolicy(fenced_files=(<planning>/abk.yaml,))` and a worktree and asserts through the terminal/create path that `echo x > <planning>/abk.yaml` and `cp /tmp/m <planning>/abk.yaml` are refused with `FENCED_REASON` and that `cat <planning>/abk.yaml` is allowed.
- [x] 2.2 Test: in `tests/cli/test_doctor_review_policy.py`, `abk doctor` warns for a protected or class glob that matches no file in any repo, fails for a class that cannot be resolved, warns for policy set while `enabled` is false, and is silent for a valid section.
- [x] 2.3 Add the doctor check for the `review` section, and document the section in `docs/configuration.md` and the `abk-config` skill, with a commented block in the `abk init` template.

## 3. [agent-build-kit] [unit-test] The review tier is stored on the unit

Done when the planner's review tier is stored on the unit and kept by a re-plan of a started unit, and a record written before this change reads as no estimate. Estimate: about 200 changed lines.

- [x] 3.1 Test: in `tests/pipeline/test_unit_store_review_tier.py`, the estimate round-trips through the store, `upsert` keeps a started unit's estimate through a re-plan and gives a new unit the one it was planned with, and a record written before this change reads as no estimate.
- [x] 3.2 Carry the review tier through `Unit` and `StoredUnit` in `pipeline/units.py` and `pipeline/unit_store.py`.

## 4. [agent-build-kit] [unit-test] The planner estimates a review tier for each unit

Done when with review enabled, the planner prompt asks for a review tier per unit and says what lowers and what raises it, a reply below a unit's floor or with an unknown value is refused naming the unit, the group and the floor, an omitted value takes the floor, and with review disabled the prompt is unchanged. Estimate: about 380 changed lines.

- [x] 4.1 Test: in `tests/pipeline/test_planner_review_tier.py`, a `[contract]`, `[narrow]` or `[acceptance]` group makes its unit's floor `full`; a group whose task text names a protected path does too; a unit takes the highest floor of its groups; a reply of `auto` for a unit with floor `full` is refused naming unit, group and floor; `light` for an unflagged unit is accepted; an unknown value is refused; an omitted value takes the floor.
- [x] 4.2 Test: in `tests/pipeline/test_planner_review_prompt.py`, the prompt with review enabled names the three tiers, says the estimate is a floor for review and sizes nothing, and with review disabled is identical to the prompt before this change.
- [x] 4.3 Add the review tier to the planner's prompt and parse in `pipeline/planner.py` with the floor check beside the other plan checks, and take the floor from the group flags and the protected set.

## 5. [agent-build-kit] [unit-test] The reviewer classifies the unit and names what drives it

Done when, with review enabled, the review prompt carries the criteria and the three tiers, the reply's `classification` and `drivers` are parsed without ever raising, a missing or unknown classification is recorded as `full`, the classification and drivers are stored with the approval, and the reply's other fields behave as before. Estimate: about 430 changed lines.

- [x] 5.1 Test: in `tests/pipeline/test_review_classification.py`, a reply with `classification: "light"` and drivers is parsed and both are kept; a reply with no classification, an unknown value, or output that is not JSON gives `full` and the reply's `approved`, `findings`, `needs_human` and `escalate` are read as before; the parse never raises.
- [x] 5.2 Test: in `tests/pipeline/test_review_prompt_classification.py`, the prompt with review enabled names the three tiers, the three criteria and that a classification can only raise the review a unit gets, requires drivers when the classification is above the planned estimate, and with review disabled is identical to the prompt before this change.
- [x] 5.3 Test: in `tests/pipeline/test_unit_store_classification.py`, a review round stores the classification and drivers with its record, a later round of the same unit replaces them, and a record written before this change reads as no classification.
- [x] 5.4 Add the two fields to the reply and to `parse_verdict` in `pipeline/stack_runner.py`, the criteria and the instruction to the review prompt in `pipeline/wiring.py`, and the storage to `record_approval` in `pipeline/unit_store.py`.

## 6. [agent-build-kit] [unit-test] The verdict is a pure function over the plan's floors

Done when a function returns the tier, the evidence tier and the reason from a unit's planned estimate, protected paths and group flags by the floors the spec names, takes the highest, makes no model call, gives the same answer for the same facts, and names the rule that decided, and treats a unit of the `integration-test` kind as a `unit-test` unit. Estimate: about 265 changed lines.

Needs: integration-test-kind-is-a-label group 1 — the test below builds a unit of the `integration-test` kind, which exists only after that group

- [x] 6.1 Test: in `tests/pipeline/test_verdict.py`, a table of units covering each floor from the plan alone (planned estimate, protected path, `contract`, `narrow` or `acceptance` flag) and the highest of several, and a unit of the `integration-test` kind gets exactly the floors the same unit as `unit-test` gets.
- [x] 6.2 Test: in `tests/pipeline/test_verdict_reasons.py`, the reason names the rule that decided, and for two equal floors names the first in the order the spec lists them.
- [x] 6.3 Add the verdict module under `pipeline/` with the tier enum and the function, taking the unit's recorded facts, the policy and the class's history, and reading no state itself; this task covers the floors from the plan, and the next group adds the rest.

## 7. [agent-build-kit] [unit-test] The verdict also reads the recorded gate results, the classification and the history

Done when the verdict function also takes a floor from each recorded gate result, an open required finding, the reviewer's classification and the class's history, the highest still wins, nothing lowers a higher floor, the evidence tier excludes the history floor, and a table of cases includes each case that must not reach `auto`. Estimate: about 300 changed lines.

- [x] 7.1 Test: in `tests/pipeline/test_verdict.py`, the table extended with each floor from the recorded results and the review (a missing or failed red-first, unit-test and e2e-test result, an open required finding, a classification, a missing classification, and a class with too few samples or a low clean rate), the highest of several, and the evidence tier excluding the history floor.
- [x] 7.2 Test: in `tests/pipeline/test_verdict_never_lowers.py`, for every combination of two floors the verdict is at least the higher, a lower classification never lowers a higher floor, and computing twice gives equal results.
- [x] 7.3 Add those floors to the verdict function, taking the class's history as an input; this task covers the floors the previous group left out.

## 8. [agent-build-kit] [unit-test] Every review round records a verdict, and nothing acts on it

Done when each review round of a unit, with review enabled, writes an entry for it to `runs/verdicts.json` with every field the spec lists, final only for the round that approves, a later round replaces it, a gate that has not yet run is pending, a failure to compute or write is logged and never stops the unit, no other module reads the file to decide anything, and the file is listed with the state files. Estimate: about 380 changed lines.

- [x] 8.1 Test: in `tests/pipeline/test_verdict_record.py`, a round that asks for rework writes one interim entry holding the unit, change, round, class, planned estimate, classification, drivers, evidence tier, tier, reason, changed paths, changed-line count and `brief` false; the round that approves replaces it with a final one; a round that holds the unit for a person leaves an interim entry only; an e2e-test not yet run is met in the interim verdict and missing in the final; the file is replaced atomically; the entry for a unit with no history uses the evidence tier and tier separately.
- [x] 8.2 Test: in `tests/graph/test_verdict_is_shadow.py`, with the state directory refusing the write, a review round ends and the unit goes on as before with one logged failure; with review disabled no entry is written; and a source search finds no reader of the verdict file outside the recording module and the status listing.
- [x] 8.3 Add the record to a new module beside the unit store, call it from the review node after each round's reply is weighed, inside a guard that logs and swallows any error, and list `runs/verdicts.json` in the state-on-disk table of `docs/architecture.md`; this task covers the record, the call and the listing, and the next group adds the two instruments.

## 9. [agent-build-kit] [unit-test] The verdict counter and the planner-accuracy metric are recorded

Done when the verdict counter and the planner-accuracy metric are recorded for each verdict and catalogued. Estimate: about 130 changed lines.

- [x] 9.1 Test: in `tests/test_metric_catalogue_verdict.py`, the verdict counter has the tier, estimate and class as attributes and no unit id, the planner-accuracy reading counts below, equal and above, and both are in the catalogue helper.
- [x] 9.2 Add the two instruments and record them where the verdict is recorded; this task covers the instruments the previous group's task left out.
