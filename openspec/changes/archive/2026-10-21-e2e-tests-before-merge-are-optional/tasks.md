# Tasks

Acceptance: none — the setting is read from configuration, the routing is a graph decision, the record, the pull request text and the verdict are pure functions over stored facts, and each is proved by a tier-1 test over fake units and a stand-in runner; `verify` is not changed beyond naming units in a failure's detail, which a test over a fake runner drives.

Priority: 1

## 1. [agent-build-kit] [unit-test] The `e2e_before_merge` setting, global with a per-repo override

Done when `global_limits.e2e_before_merge` and each repo's `tests.e2e_before_merge` load with the values `required` and `deferred`, the default is `required`, a repo's own value wins and an unset one follows the global one, a bad value is refused naming the key, `abk config` prints the value in effect, and the configuration reference, the `abk-config` skill and the `abk init` template describe it. Estimate: about 420 changed lines.

Needs: test-kinds-are-unit-test-and-e2e-test group 23 — the setting and the node are written in the e2e names
Needs: review-policy-and-verdict-recorded-in-shadow group 9 — the verdict function and its inputs exist first

- [x] 1.1 Test: in `tests/config/test_e2e_before_merge_config.py`, a file that does not mention the setting loads with `required` for every repo; `deferred` globally is followed by a repo that does not set it; a repo's own value wins over the global one in both directions; `e2e_before_merge: later` is refused naming the key and the two accepted values, at the global level and in a repo's `tests` block; the resolver gives the same answer as the pattern the e2e unit scope uses for a repo with no `tests` block at all.
- [x] 1.2 Test: in `tests/cli/test_config_cmd_e2e_before_merge.py`, `abk config` prints the global value and, for each repo that sets its own, the repo's, and prints nothing extra when none does; the `abk init` template contains the setting commented out, with its default.
- [x] 1.3 Add the setting to the global limits and to a repo's `tests` block, with the closed set of values as an enum and a resolver beside the one for the e2e unit scope, print it in `abk config`, and add a commented line to the `abk init` template.
- [x] 1.4 Document the setting, its default and its trade (a live-stack failure found after the merge instead of before it, covered only by what `verify` runs) in `docs/configuration.md`, and add a line to the `abk-config` skill and its mirror, and a changelog entry.

## 2. [agent-build-kit] [unit-test] A unit records its e2e state

Done when a passing e2e node records `passed`, a failing one `failed`, a unit-test unit reaching review records `not-required`, a rework that pushes a new head resets the state, and a unit stored before this change reads with no state. Estimate: about 200 changed lines.

- [x] 2.1 Test: in `tests/graph/test_e2e_state_recorded.py`, a passing e2e node records `passed`, a failing one `failed`, a unit-test unit reaching review records `not-required`, a rework that pushes a new head resets the recorded state before the next result is written, and a stored unit written before this change reads with no state.
- [x] 2.2 Add the stored e2e state, with its closed set of four values, to the unit and its store, record `passed` and `failed` from the e2e node and `not-required` for a unit-test unit reaching review, and reset it when a new head is pushed.

## 3. [agent-build-kit] [unit-test] A deferred unit skips the e2e node before merge

Done when with the tier deferred for a unit's repo, a unit of the e2e-test kind does not run the e2e node after review nor again on a moved base, takes no e2e lock, is pushed with its e2e state `deferred`, and a scheduled whole-suite run is unaffected. Estimate: about 280 changed lines.

- [x] 3.1 Test: in `tests/graph/test_e2e_deferred_routing.py`, with the tier deferred, a unit of the e2e-test kind approved by review goes on to the next step without the e2e node and records `deferred`; the same unit approved at an already approved head on a resumed run does the same; a unit moved onto a new base goes from the unit-test node to the next step without the e2e node; with the tier required each of the three runs the node as today; a scheduled run runs the node whichever the setting is; the e2e lock is not taken in the deferred cases.
- [x] 3.2 Make the three routing decisions that lead to the e2e node skip it for a deferred unit that is not a scheduled run, record `deferred`, and leave the node itself as it is.
- [x] 3.3 Update `docs/architecture.md` and `docs/unit-graph.md` for the edge that skips the node and the stored state.

## 4. [agent-build-kit] [unit-test] The pull request and a failed verification say what was deferred

Done when the pull request says "e2e-test deferred to verify", and a failed verification names the units that deferred. Estimate: about 240 changed lines.

- [x] 4.1 Test: in `tests/pipeline/test_pr_body_e2e_deferred.py`, the body of a unit whose state is `deferred` says "e2e-test deferred to verify" and that the live tests run after the merge against the deployed change, holds no e2e results, and keeps the text when the body is fitted to a limit far under its natural size; a unit that passed keeps its results section; a unit-test unit keeps its verification text.
- [x] 4.2 Test: in `tests/pipeline/test_verify_deferred.py`, over a fake runner and two merged units of one change of which one deferred, verification runs the same deploy commands and live tests as for a change with no deferral and a failure's detail names the deferred unit; a failure with no deferred unit has the detail it has today; a passing verification is unchanged.
- [x] 4.3 Add the deferred text to the verification section of the pull request body as a fixed section, and have a failed verification's detail name the change's units whose state is `deferred`, without changing what `verify` selects or runs.
- [x] 4.4 Update the `abk-pipeline` skill and its mirror for what a deferred unit's pull request says.

## 5. [agent-build-kit] [unit-test] The verdict reads four e2e states, and a deferred one reaches `auto` only when the policy says so

Done when the verdict's e2e input is one of `passed`, `deferred`, `failed` and `not-required`, `failed` is `full`, `deferred` holds a unit at `light` unless `review.auto_land.allow_deferred_e2e` is true, the key is read only in `auto_land` and is false by default, a missing state is read as a missing gate for an e2e-test unit, and the verdict's reasons name the state. Estimate: about 430 changed lines.

- [x] 5.1 Test: in `tests/pipeline/test_verdict_e2e_state.py`, a table over the four states with every other input green: `passed` and `not-required` add no floor and give `auto`, `deferred` gives `light` with a reason naming the deferral and an evidence tier of `light`, `failed` gives `full`; with `allow_deferred_e2e` true `deferred` gives `auto`; a deferred unit on a protected path, with a `contract` flag or with an open required finding is `full` in either setting; an e2e-test unit with no state is `full` and a unit-test unit with none is read as `not-required`; the same facts give the same answer twice.
- [x] 5.2 Test: in `tests/pipeline/test_verdict_never_lowers.py`, extend the combination check so that for every pair of floors including a deferred e2e the verdict is at least the higher of the two and the allowance never lowers a tier another floor set.
- [x] 5.3 Test: in `tests/config/test_review_config_allow_deferred_e2e.py`, the key loads false by default, loads true when set under `review.auto_land`, is refused as an unknown key under `review` and under a repo's `review` block, and is refused when not a boolean.
- [x] 5.4 Test: in `tests/pipeline/test_verdict_record.py`, extend so a recorded verdict for a deferred unit holds the evidence tier and the reason naming the deferral, and the shadow guarantee still holds: a failure to compute it is logged and does not stop the unit.
- [x] 5.5 Replace the verdict's pass-or-fail e2e input with the four-state one, read from the unit's stored state with the defaults above, add the floors and the reason text, and add `allow_deferred_e2e` to the auto-land policy model with default false and to its validation.
- [x] 5.6 Document the key and the rule in `docs/configuration.md` and the `abk-config` skill and its mirror, and say in `docs/architecture.md` that a deferred e2e result is not green evidence.
