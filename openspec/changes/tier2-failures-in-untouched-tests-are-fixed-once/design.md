# Design

## What was checked, and where

Read-only against the agent-build-kit checkout (paths under `src/agent_build_kit/`, main at `258f522`).

- `pipeline/wiring.py` `E2eSession.run` (the class holding `self._marker`; a sibling's text calls it `E2eGate`) resolves
  `toolchain.e2e_commands(where, marker=...)` per project, takes `stack_lock` once around every command, and builds a `E2eResult` whose `output`
  is the last 4000 characters. It returns `(ok, snapshot)`. When the repo has `scripts/dev-stack.sh`, `_run_on_dev_stack` runs the repo's own
  `up`/`test`/`down` instead, so no profile command or test id is involved.
- `graph/nodes.py` `e2e-test` (~1561): on failure it logs the tail, saves `e2e-test failed:\n<snapshot>` as feedback with `FeedbackSource.E2E`
  (appended to a person's own words when the feedback came from review) and stops with "e2e-test failed", or, when the base moved, restacks. The
  rework prompt is made from that feedback. `after_e2e` routes on `moved`/`restack` only.
- `isolate()` and `repeat()` are closures inside the unit-test builder in `wiring.py`: `isolate` is called only for a failed command after the first
  (`index > 0`) of a unit-test run, and `repeat` takes the commands unit-test ran. `limits.unit_test_repeat_runs` (`config.py`, default 3, 0 off) sets the
  repeat. Neither is reachable from `E2eSession`. No test says so (the research note records that it is unpinned).
- `touched_tests(tree, ref)` lists `(file, test)` for tests added or changed against `ref`. It lists test functions, not files, and not a changed
  `conftest.py` or support module.
- `profiles/python_uv.py`: `failed_tests(output)` reads failed ids from output with a regex; `serial_rerun_command(command, tests)` keeps the
  command up to the pytest program and replaces the rest with the ids and `-q`, so it also turns an e2e-test command (`... pytest -m local_stack -v`)
  into one that runs those ids alone, the marker dropped. Explicit ids select a test whatever its markers.
- `pipeline/flakes.py`: `flake_change_name` (name from the id, capped at `NAME_LIMIT` with a hash), `_open_change` / `_next_name` /
  `_candidates` (the open change, the archived earlier attempt, the successor's name), `wait_on_fix` (under `flakes.lock`: ensure the change,
  skip a unit of that change, `_add_needs` to each group of each member), `_add_needs` (under the tasks file's own lock; writes
  `Needs: <fix> group 1 merged — <why>` and skips a duplicate), `_write_change` (proposal, design stub, tasks, spec, no model), `FlakeRecord`
  (a jsonl file under the state directory with its own lock, `counts()` for status). The unit-test route is `FlakeFound` raised from `isolate`,
  caught in `graph/nodes.py` (`wait_for_fix`: `hold(PLANNED, note, cause=Cause.GATED)` then `set_gated_requeue(unit.id, RequeueReason.RESUME)`)
  and in `pipeline/events.py` for a restack. `build_on_flake` (`wiring.py`) records and calls `wait_on_fix`. `abk status` prints each flaky test
  from `flake_record(inst).counts()` (`cli/pipeline.py` ~471).
- A clean worktree at a ref already exists in two forms: `pipeline/workspaces.py` `prepare_detached(repo, name, *, ref, root)` (a detached,
  reusable checkout for running something from the default branch, which the dev stack's base uses) and `pipeline/check_runner.py` `_worktree_at(repo,
  sha)` (a detached worktree in a temporary directory, removed however the block exits, used by the red check). The restack itself works inside the
  unit's own worktree and adds none.
- `cli/pipeline.py` `_tick`: with `--dry-run` it reports the round (polling, planning, archiving still happen so the store is current), logs the
  ready units and returns before any unit is built; nothing there knows of an e2e-test failure.

## Coordination with the other e2e-test changes

- `acceptance-server-runs-in-the-scratch-environment` **group 3** adds the profile hook `parse_test_failures(output) -> list[TestFailure]`
  (`TestFailure(test, line)`) and the flags `-rfE --tb=short`, and `E2eResult.failures`, read from the whole output before it is cut to 4000
  characters. This change needs exactly that: the failed ids of a run, whole, with their first failure line. Re-parsing the cut `output` with
  `failed_tests` would lose the ids of a long run's first failures, and a second parser would be a duplicate of the hook. So the first group of this
  change carries `Needs: acceptance-server-runs-in-the-scratch-environment group 3 merged`; `merged` because both change `E2eSession.run` and
  `build_snapshot`, so stacking on that group's branch would build on a moving target. This change reads `E2eResult.failures` and `TestFailure`, and
  adds only to the result fields of its own, each defaulted so a stored result still loads.
- `tier2-time-is-recorded-per-test` adds `E2eResult.durations` and a block of text above the cut output; `acceptance-server-...` group 3 adds the
  failure listing and the output-file path to the same fixed part. This change adds no block there: a parked unit's result is not posted, and what
  it adds to a failed unit's feedback is the removal of text (below). No `Needs:` joins it to the time change.
- `tier2-lock-wait-is-configurable` and `tier2-lock-wait-holds-the-unit` change how long a unit waits for `stack_lock` and what it is held as. The
  base run happens inside the hold the unit's own run already has (below), so it never queues a second time and neither change is touched.

## Classification

After an e2e-test run fails and before anything is saved, the node asks the session to classify `result.failures`. For each failed test id, by the
file part of its identifier:

1. **The unit's own**: the file is one the branch added or changed against the unit's base, whether `touched_tests` lists it or the branch changed
   a `conftest.py` or support file beside it (the diff of file names against the same ref `touched_tests` uses). The unit fails as today. Nothing is
   run for it.
2. **Untouched**: every other test. Only these are run on the base.

A failure the profile cannot read (no ids, an output with no summary, a profile without the hook, or the dev stack path, which runs one script and
selects nothing) is classified as nothing, and the unit fails as today. The base run is never guessed at.

## The base run, once

The untouched ids are run one time, together, with `serial_rerun_command(command, ids)` for the e2e-test command that failed, in a clean detached
worktree of the ref the unit's e2e-test ran against (the base `unit-test` verifies against, `state.base or self.base`, not the unit's branch). The
worktree is `_worktree_at`'s shape (temporary, removed however the block exits) rather than `prepare_detached`'s reusable one: nothing here is
shared between units and nothing is left to move. The run is inside the `stack_lock` hold the unit's own run took, as a second step in the same
`with` block, so it is not queued behind other units and sees the same live stack. Per id, the base output decides:

- **fails there** (the id appears as `FAILED` or `ERROR` in the base run's own output): pre-existing, charged to the base;
- **passes there**: the unit's change broke it;
- **anything else** (collected nothing, the id is missing on the base, the command errored without naming the id, a timeout): not proved
  pre-existing, so the unit broke it. A test that does not exist on the base can never be a pre-existing failure.

If every untouched failure is pre-existing and the unit has no failure of its own, the unit is parked behind the fixes. If any failure is the
unit's own or broke on the base, the unit fails as today for those, and the pre-existing ones are still recorded and given their fix change so
the next unit does not pay for them, but the unit gains no `Needs:` line for them: it has its own work to fix first and meets them again on its
next e2e-test run, which then parks it if they remain.

The design does not run the base twice, repeat a test, or call `isolate` or `repeat`. `limits.e2e_base_runs` (0 or 1, default 1, like
`unit_test_repeat_runs`, in the same `limits` model; 0 turns the base run off) is a switch, not a count: the field cannot be above 1, since the cost
is tens of minutes and one run is the whole question. When off, the classification is not asked and the unit fails as today.

## The e2e-test tests are not repeated

A test pins the structural fact the research note found unpinned: `E2eSession.run`'s commands never reach `isolate` or `repeat`; with
`limits.unit_test_repeat_runs` at 3 a failing e2e-test command runs once on the unit's tree, and at most once more on the base for the untouched ids,
and the unit-test repeat's input (the commands unit-test ran) never contains an e2e-test command. The rule is that an e2e-test test is run by the e2e-test gate
alone.

## The record

`pipeline/untouched_failures.py` (a new module beside `flakes.py`, which it imports from and does not change in behaviour) defines
`PreExisting(test, unit, command, line, at, base_result, base_output, change)` and `PreExistingRecord` over
`<state_dir>/preexisting-failures.jsonl` with its own lock, the same shape as `FlakeRecord`: `append`, `entries`, `counts`. `line` is the first
failure line from `TestFailure`, `base_result` is `failed` (recorded entries are only those), and `base_output` is the last 4000 characters of the
base run, redacted by the function the sibling change that added the redaction names, when it exists (not a dependency; the record holds what
`E2eResult` already holds). `abk status` prints, beside each flaky line,
`  pre-existing: <test> — failed on the base N time(s), fix <change>`.

## One fix change per test id, previewed first

`flakes.py`'s helpers are reused by generalizing their prefix, not copied: `_candidates(test)` and `flake_change_name` take a prefix argument
(`fix-flaky` today); the new one is `fix-failing`, so a test that is both flaky and pre-existing is two kinds of change and neither suppresses the
other. The name still comes from the id, capped with a hash. `_open_change`, `_next_name`, `_add_needs` (with the reason text as an argument, since
it reads "flaky test <id>") and the lock are reused.

The ensure step, under `<state_dir>/preexisting.lock`, has two halves:

1. **Preview**: `preview(inst, test)` returns `Exists(change)` when an open change for the id exists, else `Write(name, earlier)` with the name
   `_next_name` gives and the archived earlier attempt, if any. It reads only the directory; it is what the dry run prints.
2. **Write**: only on `Write`, `_write_change` writes the change without a model: a proposal giving the test, its first failure line, that the base
   run failed too with its output, the units that met it (from the record), the module it exercises (as `_modules_of` finds from imports), and
   the earlier attempt if any; a design stub asking whether the test, the code or the environment is at fault; one group `[repo] [e2e-test]`, tests
   first, that reproduces the failure on the base deterministically, makes it pass and runs it alone under the e2e-test marker, with `Priority: 1`
   and an `Acceptance: none` line saying the run of the fixed test is the check; and a spec (ADDED, or MODIFIED for a successor, as `_spec` does for
   a flake) stating the test passes on the base.

Both kinds of fix change are written at `Priority: 1`: the flake fix change's template (`_tasks` in `pipeline/flakes.py`) carried `Priority: 2`, and
every unit that waits on either kind is held until it merges, so the fix is not queued behind the work it is blocking.

The group is e2e-test because the test is. That is the one difference from a flake's fix: the unit's e2e-test run is the confirmation, and the
fix change's own unit does not wait on itself for the same reason as a flake's (`unit.change == name`).

The preview logs `exists: <change>` or `would write: <change>` for each id before the write; the write logs `wrote: <change>` after. `abk tick
--dry-run` calls only the preview for each pre-existing failure in the record and prints the same lines, writing nothing and running no base
run. A dry run can only report what is recorded: it cannot know a failure that has not happened yet.

Two units meeting one failure in one tick make one change and two `Needs:` lines, the way two flakes do, because both take the lock and the second
finds the first's change. A successor is written only when the earlier change is merged and archived (`_archived`) and the test fails on the base
again; any unit still waiting then gains a line on the successor.

## Waiting and resuming

`wait_for_fix`'s mechanism is reused: `hold(PLANNED, note, note, cause=Cause.GATED)` then `set_gated_requeue(unit.id, RequeueReason.RESUME)`,
with a note naming the tests ("waiting for the fix of the failing test X on the base"). The `Needs:` line (`group 1 merged — failing test X on the
base`) is what `unmet_gates` holds the unit on, so the unit resumes when the fix change's group 1 merges. The thread is left where it stopped,
which is the e2e-test node, so the unit resumes there, restacked on the new base by the existing step, and e2e-test runs again in full. The hold is
taken from `e2e-test`, which today has only a restack path for a stopped run; whether the resumed thread re-enters `e2e-test` (and not the node after) is
the same property the unit-test route has and is UNVERIFIED for e2e-test (see below). A restack's unit-test (`pipeline/events.py`) is not touched.

## Feedback hygiene

`e2e-test` saves `e2e-test failed:\n<snapshot>`. When the failures were classified, the saved text is the snapshot's fixed header and only the failure
lines of tests that are the unit's (own or broke on the base) with the output blocks for them; failed lines of untouched tests are not saved, and
the pre-existing ones are named once as "also failing on the base, recorded: <ids>". When nothing could be classified the text is as today.
Because the output is one cut tail for every command, the tail is kept only if every failed test in it is the unit's; otherwise the saved text is
the listing lines alone. The same text is what a rework prompt reads, so it carries no untouched test's output.

## What is faked in tests, and why no e2e-test

Classification, the base run (a fake runner and a temporary git repository for the worktree), the record, the writer, the lock, the dry run, the
park and the resume are all decided by text and files: tests use recorded pytest output, a fake runner standing for the e2e-test command, a real
temporary git repository and planning directory, and the fake graph and unit store the unit-test flake tests use. Nothing needs the live stack, so no
group is e2e-test and `tasks.md` opts out of acceptance with a reason. The first real e2e-test failure in an untouched test is the live confirmation.

## UNVERIFIED

- **A cheap clean base worktree for e2e-test.** Adding a detached worktree is cheap, and the python profile's commands use `--isolated` per member,
  so a base worktree needs no synced environment of its own for them. A repo with no members runs `uv run pytest ...` with no `--isolated`, which
  creates an environment inside the worktree: its cost for a large repo is not measured, and a repo whose fixtures need an untracked file (a
  `.env`, built assets) that a fresh worktree lacks would fail on the base for the wrong reason, which this design reads as "not proved
  pre-existing", failing the unit as today and safe. The builder measures the clean-worktree time on this repository's own e2e-test suite and notes it
  in `docs/architecture.md`.
- **How the live stack is shared between the unit's run and the base run.** Designed as one `stack_lock` hold with the base run second, on the same
  stack the tests reach by address, not by worktree. Not confirmed: whether a failed live test leaves state in the stack (a scratch installation,
  a started agent) that makes the base run's result differ from a clean one, in either direction. A base run that fails because of state the
  unit's run left would be recorded as pre-existing wrongly; the mitigation in the design is that the record keeps the base output for a person.
  The dev stack path is not covered at all: it has no per-test selection, and the base run is skipped there (the unit fails as today).
- Whether the resumed thread lands on `e2e-test` and not past it after `hold`, as the unit-test flake route lands on unit-test.
- Whether `touched_tests` plus a diff of file names is what the builder finds the cheapest way to say "the file is the unit's"; the rule is the one
  stated above, not the helper.
- The `E2eSession` name (the checkout) against `E2eGate` (the sibling's text).

## Not included

Grouping equal failure lines; running the base for a unit whose e2e-test used the dev stack; a retry of a base run; holding a unit for a person when
an e2e-test failure names no touched test (the research note's open question: here it is classified, not held); deciding whether the fix lies in the
test or the code (the fix unit's agent decides, as for a flake); and the cause of any particular failure.
