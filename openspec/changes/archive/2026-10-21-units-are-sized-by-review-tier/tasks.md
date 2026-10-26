# Tasks

Acceptance: none — this adds configuration, a stricter plan check, planner instructions and a staleness record, each proved by a unit-test over fake plans, fake configurations and temporary state directories; nothing a consumer drives is built, and with `review.enabled` false the pipeline behaves as before.

Priority: 1

## 1. [agent-build-kit] [unit-test] The `review.ceilings` setting and the ceilings in effect

Done when the `review` section accepts `ceilings` with the three tiers and their defaults, the order and the floor are checked when the configuration loads, one helper returns the ceiling in effect for a tier, and with `review.enabled` false that helper returns the `full` ceiling for every tier. Estimate: about 290 changed lines.

Needs: review-policy-and-verdict-recorded-in-shadow group 9 — the review section, the tier a planner estimates and the verdict it feeds exist first
Needs: limits-split-into-global-and-project group 12 — the `abk config --migrate` command and its text edit exist first

- [x] 1.1 Test: in `tests/config/test_review_ceilings.py`, a workspace with no `ceilings` loads with 5000, 2000 and 750, each key loads when set, an unknown tier fails naming it, `light` above `auto` fails naming both tiers and both values, `full` above `light` likewise, and `full` at or below `min_unit_lines` fails naming the floor and both values.
- [x] 1.2 Test: in `tests/config/test_review_ceilings_flag.py`, with `review.enabled` true the helper returns each tier's ceiling for a repo, with it false it returns the `full` ceiling in effect for every tier, and a workspace that sets only `max_unit_lines` has that value as the `full` ceiling in effect under both flags.
- [x] 1.3 Add `ceilings` to the review section, the validation for the workspace's ceilings beside the existing floor check, and the helper that returns the ceiling for one tier, taking the repo it is asked for so a repo's override can be read in the next group, the only place the flag is read for sizing.

## 2. [agent-build-kit] [unit-test] A repo's `review` block can override the ceilings

Done when a repo's `review` block accepts a `ceilings` override whose unset tiers follow the workspace, the helper returns the ceiling in effect for that repo and tier, and a repo whose merged ceilings break the order or the floor fails loading naming the repo. Estimate: about 250 changed lines.

- [x] 2.1 Test: in `tests/config/test_review_ceilings_repo.py`, a repo's `review` block accepts `ceilings` with any one tier, the ceilings in effect for that repo are its own value for that tier and the workspace's for the others, a repo whose merged ceilings break the order or the floor fails loading naming the repo, the tier and both values, and a repo with no override has the workspace's.
- [x] 2.2 Add `ceilings` to the per-repo review block, the validation for each repo's merged ceilings beside the workspace check, and make the helper return a repo's ceilings and the ceiling for one of its tiers.

## 3. [agent-build-kit] [unit-test] `max_unit_lines` is deprecated and read as the full ceiling

Done when `global_limits.max_unit_lines` is the `full` ceiling when `review.ceilings.full` is not set, setting both to different values fails loading naming both, setting both to the same value loads, `abk config` and `abk doctor` say the key is deprecated for `review.ceilings.full` whenever the file or its overlay sets it, and `min_unit_lines` is unchanged. Estimate: about 330 changed lines.

- [x] 3.1 Test: in `tests/config/test_max_unit_lines_deprecated.py`, `max_unit_lines: 600` alone makes the `full` ceiling in effect 600, `ceilings.full: 600` alone does the same with no notice, both set to different values fail loading naming both keys and both values, both set to 750 load, `min_unit_lines` and its check against the `full` ceiling are as before, and the deprecated key set in the overlay file is read the same way.
- [x] 3.2 Test: in `tests/cli/test_config_max_unit_lines_notice.py`, `abk config` prints one notice naming `global_limits.max_unit_lines` and `review.ceilings.full` when the key is set, prints none when it is not, and prints the effective ceilings.
- [x] 3.3 Test: in `tests/cli/test_doctor_max_unit_lines.py`, `abk doctor` warns once for the deprecated key, says to run `abk config --migrate` or move the value to `review.ceilings.full`, and is silent when the key is absent.
- [x] 3.4 Add the mapping and the disagreement check at the workspace level, where both sections are visible, extend the deprecation listing and notice text to cover a key under `global_limits`, and print it from `abk config` and `abk doctor`.

## 4. [agent-build-kit] [unit-test] `abk config --migrate` moves `max_unit_lines` to `review.ceilings.full`

Done when `abk config --migrate` moves the value of `max_unit_lines` to `review.ceilings.full` by a text edit that changes nothing else, refuses and writes nothing in the cases it cannot edit safely, and makes the move in the same single change, confirmation and write as the moves the command already makes. Estimate: about 320 changed lines.

- [x] 4.1 Test: in `tests/test_config_migrate_ceilings.py`, the text edit turns `max_unit_lines: 900` under `global_limits` (or under the deprecated root `limits`) into `review.ceilings.full: 900`, creating the `review` and `ceilings` blocks when they are absent and placing the key in an existing `review` block in its own style; removes the old key with the comment at the end of its line and the comment lines directly above it moved with the value; changes no other byte of the file; and gives back the same text when run again.
- [x] 4.2 Test: in `tests/test_config_migrate_ceilings_refused.py`, the edit refuses and writes nothing when `review.ceilings.full` is already set to a different value, when the key's value spans lines or carries an anchor, when the file has several documents, or when the result would not load; and `tests/cli/test_config_migrate_ceilings_cmd.py` runs `abk config --migrate` over a file that holds both this move and the limits move and shows one change, asks once and writes once.
- [x] 4.3 Add the move to the text edit and to the command's one change, using the verification the existing moves use.

## 5. [agent-build-kit] [unit-test] The plan check holds a unit to the ceiling of its expected tier

Done when, with per-tier sizing on, the plan check holds a unit to the ceiling of its expected tier after calibration with a unit that has no tier held to `full`, a repo's override is the ceiling for that repo's units, a single group over its unit's ceiling is reported as needing its tasks split naming the tier, and with the flag off the plan check's messages are as before. Estimate: about 330 changed lines.

- [x] 5.1 Test: in `tests/pipeline/test_planner_tier_ceilings.py`, with the flag on, a unit expected to get `auto` at 2000 lines is accepted and one at 5200 is refused naming `auto` and 5000, a `light` unit at 2100 is refused naming `light`, a ratio of 1.5 on an `auto` unit at 3500 is refused with 5250, 5000, the ratio and its samples named, a unit with no expected tier at 800 is refused against 750, and a repo's override is the ceiling for that repo's units.
- [x] 5.2 Test: in `tests/pipeline/test_planner_tier_single_group.py`, a single group over its unit's ceiling raises the too-large error naming the group and the tier and saying its tasks must be split, and is reported before any combined unit.
- [x] 5.3 Test: in `tests/pipeline/test_planner_flag_off_unchanged.py`, with the flag off the plan check's messages are unchanged.
- [x] 5.4 Make the plan check and the join check's ceiling argument ask the one helper for the ceiling of the unit's tier.

## 6. [agent-build-kit] [unit-test] The planner is told each tier's ceiling and a pull request's size is compared with its tier's

Done when, with per-tier sizing on, the planner's instructions state each tier's ceiling and each overriding repo's, the calibration text's largest raw estimate is computed from the unit's tier, a pull request's actual size is compared with its tier's ceiling, and with the flag off every prompt, message and status line is as before. Estimate: about 320 changed lines.

- [x] 6.1 Test: in `tests/pipeline/test_planner_tier_prompt.py`, with the flag on the instructions give the three ceilings and a repo's override, say a unit is held to its expected tier's ceiling and say the planner plans to those figures, and the calibration section's largest raw estimate for a kind is the ceiling of the unit's tier divided by the ratio.
- [x] 6.2 Test: in `tests/pipeline/test_planner_flag_off_prompt_unchanged.py`, with the flag off the prompt is byte for byte the text it was before this change for a workspace with and without a calibrated kind.
- [x] 6.3 Test: in `tests/pipeline/test_unit_size_tier_ceiling.py`, the comparison of a pull request's actual size with the ceiling uses the unit's expected tier with the flag on and the old ceiling with it off, and the log line when a pull request lands over it and the status entry name the figure used.
- [x] 6.4 Make the instructions and the actual-size comparison ask the one helper for the ceiling of the unit's tier, and add the ceilings to the instructions.

## 7. [agent-build-kit] [unit-test] A group that expects full review stays out of a unit with other work

Done when a plan that puts a group whose floor is `full` in a unit with a group whose floor is lower is refused naming the unit and the groups, and the instructions say to keep such a group apart. Estimate: about 250 changed lines.

- [x] 7.1 Test: in `tests/pipeline/test_planner_full_separation.py`, a group naming a protected path in its task text and an unflagged group in one unit refuse the plan naming the unit and both groups, two groups whose floors are `full` in one unit are accepted by this rule, a `contract` group with an ordinary group is refused, and a plan with each in its own unit is accepted; with the flag off no unit is refused by this rule.
- [x] 7.2 Test: in `tests/pipeline/test_planner_full_separation_prompt.py`, with the flag on the instructions tell the planner to keep a group it expects to get full review in a unit with only such groups and say why, and with it off the instructions are as before.
- [x] 7.3 Add the separation check beside the other plan checks and add the rule to the planner's instructions with the flag on.

## 8. [agent-build-kit] [unit-test] A join takes the highest tier

Done when a join onto a unit takes the higher tier of the two and is held to that tier's ceiling after calibration, and a join that would mix a floor-`full` group with a lower one is refused. Estimate: about 230 changed lines.

- [x] 8.1 Test: in `tests/pipeline/test_unit_joins_tier.py`, joining a unit expected to get `light` onto one expected to get `auto` makes a unit held to 2000 and a combined 2500 is refused naming `light` and 2000, two `auto` units combined at 2500 are accepted, a group counts at its floor, a calibration ratio applies to the receiving unit's kind, a join that would mix a floor-`full` group with a lower group is refused, and with the flag off the join is held to the old ceiling.
- [x] 8.2 Add the separation check to the join check and compute a joined unit's tier from the two sides.

## 9. [agent-build-kit] [unit-test] A plan records the sizing it was made under

Done when a plan's record carries a digest of the sizing configuration, empty with the flag off, and a plan whose digest is not the current one reads as stale. Estimate: about 200 changed lines.

- [x] 9.1 Test: in `tests/pipeline/test_plan_sizing_digest.py`, the digest is empty with the flag off, equal for equal configurations, different when a ceiling, the floor, `max_unit_lines`, a repo's review block or the flag changes, and a record with no digest reads as empty, so a plan recorded before this change is not stale with the flag off and is stale once it is on.
- [x] 9.2 Compute the digest from the review section, the floor and `max_unit_lines`, store it on every recorded plan, and compare it where plans are read.

## 10. [agent-build-kit] [unit-test] A stale plan is reported by the tick, `abk replan` and `abk status`

Done when the tick neither replans a stale plan nor counts it as work and says which changes are stale, `abk replan` with no argument marks stale ones, `abk status` counts them, and `abk replan` naming a change records the current digest. Estimate: about 330 changed lines.

- [x] 10.1 Test: in `tests/cli/test_plan_stale_tick.py`, with a current `tasks.md` hash and a stale digest the tick makes no planner call, says the plan is stale naming the change and `abk replan`, does not count it as work so an otherwise idle tick has none, and a change whose `tasks.md` changed is planned and recorded with the current digest.
- [x] 10.2 Test: in `tests/cli/test_replan_stale.py`, `abk replan` with no argument lists a stale plan as stale and a current one as before, naming a stale change plans it and records the current digest, and the digest is also recorded for a change whose groups were all taken so nothing was asked of the planner.
- [x] 10.3 Test: in `tests/cli/test_status_stale_plans.py`, `abk status` says how many plans are stale and names them, and prints nothing about it when none is.
- [x] 10.4 Report staleness from the tick, `abk replan` and `abk status` without changing what makes the tick plan.

## 11. [agent-build-kit] [unit-test] The documents and skills explain ceilings by tier and stale plans

Done when `docs/configuration.md` and the `abk-config` skill document `review.ceilings`, the per-repo override, the deprecation of `max_unit_lines` and the flag that gates it, the `abk-authoring` skill says a group no longer has to be split to fit a ceiling and says what to state so a tier can be estimated, `docs/cli.md` and the `abk-pipeline` skill describe stale plans and the listing, `docs/architecture.md` describes how a unit is sized, and a document test keeps each of them from drifting. Estimate: about 340 changed lines.

- [x] 11.1 Test: in `tests/docs/test_review_ceilings_docs.py`, `docs/configuration.md` and the `abk-config` skill name `review.ceilings`, its three defaults, the repo override and the deprecated `max_unit_lines`, the `abk-authoring` skill names what a group should say about the files and paths it touches and says it need not be split to dodge a size ceiling, `docs/cli.md` and the `abk-pipeline` skill name the stale listing, and `docs/architecture.md` says a unit is sized by its expected tier.
- [x] 11.2 Update the documents and the three skills' text, replacing the single-ceiling wording in the configuration reference with the ceilings, and add a changelog entry saying the keys exist, `max_unit_lines` is deprecated, and nothing is sized differently until `review.enabled` is turned on.
