# Tasks

Acceptance: none — every behaviour here is a command's output or a file edit over a temporary planning repo, a stand-in planner and a stored unit file, each proved by a tier-1 test that runs `main()` through the existing replan driver; nothing a consumer drives is built beyond what those tests drive.

Priority: 1

## 1. [agent-build-kit] [unit-test] Stale plans are found and shown

Done when a plan recorded under other ceilings or another `review:` section than the ones in force reads as stale in `abk status`, in the `abk replan` listing and in the tick's log, and a tick never plans a change for that reason and does not count it as work. Estimate: about 300 changed lines.

Needs: units-are-sized-by-review-tier group 10 — migration acts on the stale plans the sizing digest detects
Needs: limits-split-into-global-and-project group 12 — the `abk config --migrate` command and its text edit exist first

- [x] 1.1 Test: in `tests/cli/test_plan_staleness.py`, a plan record with a policy digest equal to the current one is current; one with no policy digest, or a different one, is stale and the reason says whether the ceilings, the review section or the absence of a digest caused it; a record made stale by the policy and not by the text does not make `has_work` true; a tick over three stale plans makes no planner call and logs each as stale.
- [x] 1.2 Test: in `tests/cli/test_status_stale_plans.py`, `abk status` prints one line for each stale plan naming the change and the reason, prints none for a current plan, and still prints the lines for a plan that waits for an outage.
- [x] 1.3 Test: in `tests/cli/test_replan_listing_stale.py`, `abk replan` with no arguments adds `stale` and the reason to the state of a stale plan, and keeps its existing wording and exit status 2 for every other state.
- [x] 1.4 Read the policy digest the sizing change records from the plan record, decide staleness from it apart from the text's digest, show it in the status and listing, make the tick log it and not plan for it, and keep it out of what keeps ticks busy.

## 2. [agent-build-kit] [unit-test] `abk replan --report` shows what a replan would do

Done when `abk replan --report` prints for each change its plan state, its started and unstarted units, whether a replan would call the planner and the total, making no model call and writing nothing. Estimate: about 300 changed lines.

- [x] 2.1 Test: in `tests/cli/test_replan_report.py`, over a change with one merged, one running and two planned units, `abk replan --report` names the change, says two started and two unstarted, gives the groups each unit carries, and says a replan would call the planner once; a change whose every group is taken is reported as asking nothing of the planner; the total adds the changes; with `--all` every active change is listed; the unit store, the plan records and every other file under the state directory are unchanged byte for byte; the planner is never called; a name that is not a change is refused as `abk replan` refuses it.
- [x] 2.2 Add `--report` to `abk replan`, printing for each selected change the state, the counts of started and unstarted units, the groups carried, whether the planner would be called and the total, with no write and no model call; document it in the replan section of `docs/cli.md` and the `abk-pipeline` skill's status row.

## 3. [agent-build-kit] [unit-test] `abk replan --dry-run` shows the units each change would get

Done when planning a change can be computed apart from being applied, and `abk replan --dry-run` asks the planner and prints for each change the units it would store with their ids, groups, expected review tier and estimated lines against that tier's ceiling and the units that would become `unplanned`, writing no stored file. Estimate: about 390 changed lines.

- [x] 3.1 Test: in `tests/cli/test_replan_dry_run.py`, over a change planned as four 150-line units and a stand-in planner returning one unit expected `light` of 600 lines, the output lists that unit with its tier and `600 of 2000`, lists the four old units as becoming `unplanned`, and prints the planner-call count before the call; the unit store, `planned.json` and every other file under the state directory are unchanged byte for byte afterwards, also when the planner fails and when it is refused.
- [x] 3.2 Test: in `tests/cli/test_replan_dry_run_matches.py`, for one fixture and one planner reply, the units a dry run prints are the units a replan then stores, and the planner was called once by each.
- [x] 3.3 Separate asking for and checking a plan from storing it, so the plan a call returns can be shown, then stored or discarded without a second call, and keep a tick's planning pass as it is.
- [x] 3.4 Add `--dry-run` to `abk replan`, running the planning code against copies of the unit store and the plan records in a temporary directory and printing the units with tier, estimate against ceiling and drops, in the same style as the differences a replan prints, and document it in `docs/cli.md`.

## 4. [agent-build-kit] [unit-test] A dry run shows the kept units and the joins and prints a refused plan with its reason

Done when `abk replan --dry-run` prints the started units it leaves alone and the joins, prints a refused plan with its reason and the unit ids the planner returned, says a change waits when the planner is unavailable, and refuses `--forget` as a usage error. Estimate: about 250 changed lines.

- [x] 4.1 Test: in `tests/cli/test_replan_dry_run_started.py`, a change with a merged unit and a unit in review prints each as kept with its state, the planner is told their groups are built, and only the unstarted remainder appears as units it would store; a join in the plan is printed with the unit it would be added to and the estimate before and after.
- [x] 4.2 Test: in `tests/cli/test_replan_dry_run_refused.py`, a reply that claims a group a merged unit has built prints the refusal reason and the unit ids the planner returned and exits 1, and a planner outage prints that the change waits and uses no attempt, writing nothing; `--dry-run` with `--forget` is a usage error.
- [x] 4.3 Print the kept units and the joins, the refusal reason and the returned unit ids and the outage line in a dry run, and refuse `--dry-run` with `--forget`, in the same style as the differences a replan prints.

## 5. [agent-build-kit] [unit-test] A replan lists what it would drop and keeps the old plan when refused

Needs: fix-flaky-tests-cli-test-tick-scheduling-projects-py-test-one-f3069be7 group 1 — flaky test tests/cli/test_tick_scheduling_projects.py::test_one_project_starts_its_next_unit_as_one_of_its_builds_ends_and_the_other_does_not

Done when a replan that would leave a unit `unplanned` lists it and applies nothing for that change without `--accept-unplanned`, and a refused or failed plan leaves the stored units as they were and the change still reading as stale with its reason printed. Estimate: about 380 changed lines.

- [x] 5.1 Test: in `tests/cli/test_replan_accept_unplanned.py`, a new plan that omits two planned units lists both with their ids, states and groups, stores nothing for that change and exits 1 without `--accept-unplanned`; with it, the plan is stored and both are `unplanned`; a plan that drops nothing needs no flag; in each case the planner was called once for the change; two selected changes are decided apart, one applied and one not.
- [x] 5.2 Test: in `tests/cli/test_replan_refused_keeps_plan.py`, over a stale change and a reply the checks refuse, the stored units are unchanged, the output gives the reason and says the old plan stands, the plan record has used one attempt and still carries the old policy digest so the change reads as stale, and a change that has used `max_plan_attempts` is given up and named for `--failed`.
- [x] 5.3 Test: in `tests/cli/test_replan_partly_started.py`, a change with a merged unit, a unit in review and two planned units replanned under a larger ceiling keeps the first two with state, branch, pull request and history, reports them as kept, marks their groups as built in what the planner is shown, and takes the new shape only for the planned two.
- [x] 5.4 Make a replan hold back the application of a plan that would drop units until they are accepted, print the list, and exit 1 for a change not applied; keep the previous policy digest in the record of a plan that failed or was refused.
- [x] 5.5 Add `--accept-unplanned` to `abk replan` and document it in `docs/cli.md`.

## 6. [agent-build-kit] [unit-test] `abk replan --stale --limit N` migrates by priority

Needs: fix-flaky-tests-cli-test-tick-scheduling-projects-py-test-one-f3069be7 group 1 — flaky test tests/cli/test_tick_scheduling_projects.py::test_one_project_starts_its_next_unit_as_one_of_its_builds_ends_and_the_other_does_not

Done when `abk replan --stale --limit N` plans the most urgent stale changes first and skips and lists those that wait or have given up. Estimate: about 270 changed lines.

- [x] 6.1 Test: in `tests/cli/test_replan_stale_limit.py`, with five stale changes of which two carry `Priority: 1`, `--stale --limit 2` plans exactly those two and lists the other three as not yet planned; equal priorities go by name; a change waiting for an outage with its next try ahead, and a change that has given up on its current text, are skipped and listed with the reason and `--failed` named; with a planner that reports the service unavailable on the first change the run stops, says the rest were not tried, and uses no attempt.
- [x] 6.2 Add `--stale` and `--limit N` to `abk replan`, order the selection by the most urgent priority among each change's groups and then by name, skip and list the changes the attempt and wait handling already excludes, stop at the first outage, and document the options and the migration order in `docs/cli.md` and the `abk-pipeline` skill.

## 7. [agent-build-kit] [unit-test] `abk tags --fix` rewrites the old test-kind tags

Done when `abk tags --fix` rewrites `[unit-test]` and `[e2e-test]` in group headings of open changes to `[unit-test]` and `[e2e-test]` leaving every other byte as it was, verifies the result parses to the same groups, and refuses and writes nothing for a change it cannot be sure of. Estimate: about 400 changed lines.

- [x] 7.1 Test: in `tests/cli/test_tags_fix.py`, headings `[unit-test]` and `[e2e-test] [acceptance]` become `[unit-test]` and `[e2e-test] [acceptance]`; a sentence "this is a unit-test concern" in a task, a code span with `e2e-test` and a heading's title containing `unit-test` are untouched; the output counts the tags rewritten per change; a second run reports it unchanged and writes nothing; a file with carriage-return line endings keeps them on every line; a file with no trailing newline keeps that; `--all` handles every open change and skips archived ones.
- [x] 7.2 Test: in `tests/cli/test_tags_fix_refuses.py`, a change with another tag error (an unknown repo) is refused with that reason and unchanged; a change refused among three does not stop the other two being rewritten and the exit status is 1; a read-only file and a file that is not valid text are refused naming the reason; a rewrite whose parse differs from the original's in any group's repo, flag, title, tasks or kind is refused and unwritten; the write is atomic, so a failure part way leaves the original.
- [x] 7.3 Test: in `tests/cli/test_tags_fix_dry_run.py`, `--dry-run` lists what would be rewritten and writes no file, and `--fix` with no change and no `--all` is a usage error.
- [x] 7.4 Add the text edit that finds the heading lines the parser reads and replaces only the test-kind tag, with the parse comparison and the refusals, as a mode of `abk tags`, and document `abk tags --fix` in `docs/cli.md`.

## 8. [agent-build-kit] [unit-test] A rewritten `tasks.md` does not make a plan stale and the pipeline never rewrites it

Done when the digest of a `tasks.md` is the same for the old and the new spelling of the test-kind tag so `abk tags --fix` does not make a plan stale, and no tick, replan or planning pass writes a `tasks.md`. Estimate: about 200 changed lines.

- [x] 8.1 Test: in `tests/pipeline/test_work_graph_digest_tag_spelling.py`, the digest of a `tasks.md` is the same for the old and the new spelling of the test-kind tag, a plan recorded from the old spelling counts as current for the rewritten text, and a tick after `abk tags --fix` makes no planner call.
- [x] 8.2 Test: in `tests/cli/test_tasks_md_never_written.py`, a tick, a replan and a planning pass over changes with old tags leave every `tasks.md` byte for byte unchanged.
- [x] 8.3 Make the digest ignore the tag's spelling and a recorded digest of the old text count as current.

## 9. [agent-build-kit] [unit-test] The text edit renames the old test-kind settings

Done when the text edit behind `abk config --migrate` renames each old test-kind key in an abk.yaml (`unit_test_*` to `unit_test_*`, `e2e_*` to `e2e_*`, `tests.e2e_marker`, `e2e_runtimes`, `e2e_splits`, in the workspace's blocks and in each repo's) to its new name changing no other byte, refuses and writes nothing when it cannot edit safely, and is idempotent. Estimate: about 300 changed lines.

- [x] 9.1 Test: in `tests/test_config_migrate_test_kind_keys.py`, a file holding `e2e_lock_wait_seconds: 600` under `global_limits`, `e2e_schedule: weekly` in a repo's `tests` block and a top-level `tests.e2e_splits` mapping comes back with each key renamed and its value, end-of-line comment and the comment lines above it unchanged, no other byte changed, and the same text when run again; values are never renamed, only keys.
- [x] 9.2 Test: in `tests/test_config_migrate_test_kind_keys_refused.py`, the edit refuses and writes nothing, naming the file and key, when a file holds the old and the new spelling of one setting, when a key has an anchor or a merge key, when the block is in flow style, when the file has several documents, or when the renamed file would not load with the same settings.
- [x] 9.3 Add the rename to the text edit, from the compatibility module's table of old and new keys, using the verification the existing moves use.

## 10. [agent-build-kit] [unit-test] `abk config --migrate` makes the rename in its one change

Done when `abk config --migrate` makes the rename in the same single change, confirmation and write as the moves the command already makes, and over a file that needs none says so and writes nothing. Estimate: about 220 changed lines.

- [x] 10.1 Test: in `tests/cli/test_config_migrate_test_kind_keys_cmd.py`, `abk config --migrate` over a file that needs this and the other moves the command makes shows one change, asks once and writes once with a backup, and over a file that needs none says so and writes nothing.
- [x] 10.2 Add the rename to the command's one change.

## 11. [agent-build-kit] [unit-test] The authoring guidance and the docs describe the migration

Done when the `abk-authoring` skill says groups need no splitting to dodge a 750-line ceiling and must say what they touch so a tier can be estimated, the skill's source and its mirror agree, the migration steps are in `docs/cli.md` and the `abk-pipeline` skill, and a changelog entry says what is new. Estimate: about 280 changed lines.

- [x] 11.1 Test: in `tests/skills/test_abk_authoring_ceilings.py`, the skill's text says a group need not be split to fit a single ceiling, says the planner sizes a unit by the review tier it expects, says a group names the files, boundaries or behaviours it touches, and contains no advice to split to stay under 750 lines; the source skill and the mirror in `.claude/skills` hold the same paragraph.
- [x] 11.2 Test: in `tests/docs/test_migration_documented.py`, `docs/cli.md` documents `--report`, `--dry-run`, `--stale`, `--limit` and `--accept-unplanned` under `abk replan` and `--fix` under `abk tags` and the settings it moves under `abk config --migrate`, and the changelog's unreleased section has an entry naming them.
- [x] 11.3 Add the guidance to the `abk-authoring` skill, keeping the rule that a group says what it touches without naming functions, sync the mirror, add a short "migrating open changes" section to `docs/cli.md` giving the order (`--report`, `--dry-run`, then `--stale --limit N`, and `tags --fix` first), and add the changelog entry.
