# Design

Code references are to `<home>/agent-build-kit` at commit `fdb1034`, read only. Anything not read there is marked UNVERIFIED.

## Where the full suite runs today after a move

- **Before a push** (`verify_base`, `graph/nodes.py:1761`). The branch is moved onto the fresh base without the resolver
  (`restack_onto(..., resolve=False)`, built by `build_restack_onto`, `pipeline/wiring.py:2160`). A conflict or a resolution goes to `rebase`
  (`nodes.py:1790-1792`); a clean move logs `moved onto <base> cleanly; tier 1 again` (`nodes.py:1793`) and returns `moved: True`.
  `after_verify_base` (`nodes.py:2230`) sends a moved unit to the `tier1` node, whose body (`nodes.py:1611`) calls
  `r.run_tier1(cwd, base, whole_repo=state.produced_nothing)`. Its failure on a moved unit goes back to `rebase` (`nodes.py:1648`); the move
  keeping the approval is `build_restack_onto` recording it when the diff is byte-for-byte unchanged (`wiring.py:2224-2230`). A tier 2 unit then
  runs `tier2` ("tier 2 again on the moved commit", `nodes.py:1663`).
- **After a merge releases a dependent** (`events.restack`, `pipeline/events.py:1395`). A move with no resolution and an unchanged diff runs
  `tier1(cwd=..., base=...)` (`events.py:1554`) before it pushes; a changed diff or a resolution is planned for review instead
  (`events.py:1522-1545`). A flake there parks the unit as in the graph (`events.py:1555-1572`).
- **The runner** is `build_tier1` (`wiring.py:741`): `tier1(cwd, base, whole_repo, failed_output)`. With `checks.affected.mode` on and a
  `failed_output`, it builds a selected plan (`selection`, `wiring.py:890`), runs it (`run_selection`, `wiring.py:922`), and confirms a pass with
  the full suite (`wiring.py:791-816`). Otherwise `full` runs lint and each project's `test_commands` (`full`, `wiring.py:818`). A failure in `full` calls
  `isolate` (`wiring.py:945`), which runs the failed tests alone and serially `FLAKE_RERUNS` (2, `wiring.py:140`) times and raises `FlakeFound`
  when they pass each time.
- **The hook** is `SelectsAffectedTests.affected_test_commands(repo, changed_files, failed_ids, *, seed)` (`profiles/base.py:148-158`): the
  commands that run the affected tests, an empty list when none is, `None` when the profile cannot say. `RepeatsTests.repeat_command(command,
  tests)` (`base.py:135-145`) builds a run of exactly the given test identifiers. `touched_tests(tree, ref)` (`wiring.py:2413`) lists the tests a
  tree adds or changes against a ref. `limits` is `LimitsConfig` (`config.py:297`, `tier1_repeat_runs` at `config.py:365`).
- **What the pipeline does to merge** (`docs/architecture.md` step 9, and the forge adapters' `merge_guard`, `forges/base.py:331`): it pushes the
  branch and opens or updates the pull request and never merges it; a person merges. CI runs `uv run --group dev poe test` on every pull request
  and on pushes to the trunk (`.github/workflows/ci.yml:3-40`), the full suite, and pre-commit on all files. Whether merging requires that check
  is a property of the host's branch protection, not of this repository's code: UNVERIFIED for any given installation, and the reason `merge_guard`
  reports what protection exists.
- **The Python profile has no implementation of the hook yet.** `grep affected_test_commands` finds only the protocol and the runner's call; the
  profile that would answer is `affected-tests-in-fix-rounds` group 2, not ticked in its `tasks.md`. Until it merges, every profile answers
  `None`, which this change treats as "run the full suite", so the change is correct before then and saves nothing before then.

## The measured motivation

From one installation's run logs and ledger over six days (196 units, 45 `base_changed` events); the figures are measured, and each has a limit:

- **38** clean moves logged "moved onto main cleanly; tier 1 again" at the check before a push. Limit: this counts the before-push check only, not
  the moves made by the merge handler or at the start of a run; and it counts moves, not minutes.
- **About 4 minutes each**: the parallel suite 140 to 180 seconds, the serial pass 55 to 65 seconds, plus pre-commit; about 2.5 hours in all.
  Limit: this installation's suite and host; a faster suite saves less, and the figure is wall time, not a saving, since a scoped run still costs
  lint and its selected tests.
- **15** holds "held: tier 1 failed on main; resuming at its restack". Limit: they are not classified; 7 of them are one changelog-format test
  failing for a reason that is a separate, deferred item, which this change does not touch and which a scoped run would still meet (the test
  checks a file every move can change), so the saving on holds is smaller than 15.
- Git mechanics are fast (about 0.1 minute for `prepare`); the cost is what follows the move, plus latency for a held unit (`queue_full` waits
  averaged 39 minutes and `slot` waits 19). Limit: waits are scheduling, not tier 1.
- No measurement exists of how much a scoped run saves. The suite's tests mostly go through a few central modules, so a move that brought in a
  central module is expected to select nearly everything, and the saving is expected for moves over leaf modules and documentation. Hence the
  setting, and the log line that makes the saving readable afterwards.

## The scope rule

A **moved base** is a move with no conflict and no resolution whose diff is unchanged (the condition both paths above already test before running
tier 1). Only a moved base is scoped; every other run of tier 1 is as today. Let **own files** be the files the unit changes against its base
(`_changed_files`, `wiring.py:736`), and **incoming files** the files that differ between the old base and the new base
(`git diff --name-only <old base> <new base>`; the old base is the `old_base` that `build_restack_onto` already computes, carried on the
state as `moved_from`; the merge handler has its `old_base` at `events.py:1395`).

The check is **scoped** when `limits.restack_check` is `affected` and none of these holds, and **full** otherwise:

1. an incoming file is also an own file (the move touched a file the unit changed, even when git merged it cleanly: a clean merge of two
   hunks in one file says nothing about whether the result is right);
2. the profile answers `None` for any project (it cannot say, or cannot place a changed file);
3. a selected command cannot run;
4. the unit produced nothing of its own (`whole_repo`), which is judged on the tip.

When scoped, tier 1 runs lint on the moved diff exactly as today (it is diff-scoped and cheap; this is the pre-commit step), then for each
project:

- **own**: the tests the unit added or changed (`touched_tests`), run by `repeat_command` over the project's test commands, so the unit's own
  tests are never skipped;
- **affected**: the commands from `affected_test_commands(project, own files + incoming files, [], seed=...)`. The profile is asked once with the
  union, so its answer covers both "tests that run what the move brought in" and "tests that run what the unit changes"; a test that imports a
  changed module is selected by its import or its coverage, whichever the profile uses. The framework does not read an import graph. The
  overlap restriction in the design brief (only incoming files that overlap the unit's files or their dependencies) is the profile's to apply and
  is not required of it: asking for the union can only select more tests, never fewer, so it is the safe reading.

The tests are the union of own and affected. A test selected by both runs twice in the log's counts (UNVERIFIED how the Python profile's commands
deduplicate; the counts say what each command ran, which is what the reader needs).

**Why the semantic conflict with no textual overlap is caught**: a function signature changed on the base side and called on the unit's side puts
the base's file among the incoming files and the unit's file among the own files, with no shared path, so rule 1 does not fire. Selection is by
the profile: the unit's own tests run the unit's callers, and tests that run the changed module are selected by the profile from the incoming
file. A test that exercises the call fails, and the unit is not pushed on a green it did not earn. The limit is what the profile can see: a
caller no test runs is not caught here, and is not caught by the full suite either.

## A failure in the scoped run

The scoped run reuses `isolate` (`wiring.py:945`) unchanged: a failed test is run again alone and serially (`FLAKE_RERUNS` = 2 times); the
brief's "once" is satisfied by the first rerun, and the second is the existing rule, kept to share one definition of a flake with the other
paths. A test that fails in any rerun is not a flake: the failure stands and the unit is held as today (`rebase` from the graph, an error from
the merge handler), with the scoped run's output as the feedback. The repeat of tests the unit added (`tier1_repeat_runs`, `repeat`,
`wiring.py:851`) runs on a scoped run as on a full one, over the same ids. This rerun is tier 1 only: tier 2 is never repeated or isolated.

A test that passes alone is a **flake on the moved base**. Today `FlakeFound` records it, writes one fix change per test, and parks the unit gated
on that change (`wait_for_fix`, `nodes.py:1279`; `events.py:1555`). For a scoped run the record and the fix change are made as today, but the unit
does not wait: the move did not cause the failure, the suite still runs in CI, and a hold would cost a restack round and a tick for a test that
passes alone. The unit keeps going to the push. Two limits: a flake in a test the unit added or changed (rule `own` above) is not excused (a new
test has no excuse to be flaky, the `flaky-tests` rule), it fails the run; and the unit of the flake's own fix change, which already has nothing
to wait on, behaves as today.

Doing this needs the flake callback (`on_flake`, `wiring.py:1019`) to record and ensure the change without adding `Needs:` lines to the unit's
groups, as `on_preexisting` already takes `wait` (`wiring.py:1036`). That argument is added to `on_flake` and `wait_on_fix`; a full run's call
sites keep `wait=True`.

## The log

One line in the unit's run log, written where the tier 1 result is logged: `moved base: ran <selected> of <total> tests (own <a>, affected
<b>)`; or `moved base: ran the full suite (<reason>)` with the reason from the rules above. The counts come from the runner's summary line through
the profile (`parse_test_summary`, `profiles/python_uv.py:293`); the total is the unit's last full tier 1 run's count, kept on the run state.
UNVERIFIED: that the last full run's count is available on the state across a resume; when it is not the line omits `of <total>` and keeps the
rest.

## Where the full suite remains

- **CI**: every pull request and the trunk run the whole suite (`ci.yml`). A scoped local run is a gate against pushing a branch that is visibly
  broken, not the check that decides a merge.
- **Before a merge**: nothing in the pipeline merges. A unit reaches `in_review` by `open_pr` (`nodes.py:1835`, `IN_REVIEW` at `nodes.py:1898`) after its push; a person merges
  after CI. Whether CI is required for that merge depends on the host's branch protection; this change does not weaken it and does not replace it.
  A repo that wants the local run to stay a full copy sets `limits.restack_check: full`.
- **Every other tier 1 run**: the first check, fix rounds, the gate before review (`checks`), a unit that produced nothing, and any move that
  resolved a conflict or changed the diff (which go through review and its own checks).
- **Tier 2**: unchanged. A tier 2 unit whose base moved runs tier 2 again on the moved commit (`nodes.py:1663`) exactly as today, and the scoped
  tier 1 runs before it. Tier 2 is never scoped, repeated or isolated by this change.

## Settings

`limits.restack_check` in `LimitsConfig` (`config.py`): `affected` (default) or `full`. It is a `StrEnum`-typed field like the other closed
sets. `full` runs a moved base's tier 1 exactly as before. The existing per-repo `checks.affected` mode is not consulted: it controls fix rounds,
and a moved base's scope is a separate decision with its own switch. UNVERIFIED: that no installation has set `checks.affected.mode: command` and
would expect it to govern here too; the `command` template needs `{failed_ids}`, which a moved base has none of, so in `command` mode the moved
base runs full.

## Risks

- **A missed test.** Selection can miss a test that depends on the move through something the profile cannot see (a data file, a generated
  artifact). Mitigations: rule 1, the profile answering `None` for a file it cannot place, CI on the pull request, and the setting. The
  alternative, the full suite on every move, is what costs 2.5 hours in six days.
- **A sparse first run.** A profile that selects by recorded coverage has none for a unit whose first full run did not record, and answers
  `None` (`affected-tests-in-fix-rounds` design), so the full suite runs; the saving appears once data exists.
- **No saving until the profile hook lands.** Stated above.

## Not done

The changelog merge fix; scoping any tier 1 run other than a moved base's; changing tier 2; resolving a conflict differently (other changes).
