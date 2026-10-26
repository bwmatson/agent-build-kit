# Design

## Where the flow is today

The graph runs `implement`, then `checks` (the tier 1 gate on the committed branch), then `review`. A failed `checks`
saves the output as the unit's feedback and goes to `fix_checks`, where the build agent fixes it and commits, and the
graph returns to `checks`, which runs lint and the tests again in full. Rounds are capped by `max_check_rounds`. A rework
after review also returns to `checks`. The `tier1` node (a unit that produced nothing, or a branch moved cleanly onto a
new base) is a separate use of the same runner and always runs in full.

Tier 1 is built once per repo (`build_tier1` in `pipeline/wiring.py`): the profile's lint command, then its test commands
for the changed files, run in each project's directory, a non-zero exit returning the failure text.

## The hook

`ToolchainProfile` gains, beside `test_commands`:

`affected_test_commands(repo, changed_files, failed_ids, *, seed) -> list[list[str]] | None`

`None` means the profile cannot say, which is the answer a profile gives until it implements the hook (the Node profile
is still a stub). A returned list is the commands that run the affected tests; it may be empty, meaning nothing is
affected, which the pipeline treats as a selected run that passed with zero tests, never as a pass for the unit.
`seed` is the path the profile may keep selection data in (see below). The hook is optional on the protocol, so a profile
written before it exists behaves as `None`.

## The configuration

Per repo, under the repo's entry in the workspace file: `checks.affected.mode` is `off`, `profile` or `command`
(default `off`) and `checks.affected.command` is a template. `RepoConfig` (`config.py`) is where the repo's `tests`
block already lives and gains a `checks` block beside it; it is a frozen model like its neighbours. The template is
substituted with two placeholders: `{changed_files}`, the files the branch changes since its base, and `{failed_ids}`,
the identifiers of the tests that failed in the check being fixed. Each is expanded to separate, shell-quoted arguments.
Examples of what a stack would put there are its test runner's related-files option, a per-package test run, or an
affected-projects command. A `command` mode with no template is rejected when the configuration loads. The template runs
in the same project directory as the repo's tier 1 commands, under the same time limit.

`profile` mode with a profile that returns `None` runs the full suite and says so in one line of the run log; it does not
fail.

## The flow

Only in the fix loop. Let a round be "a check ran after a fix, or after a rework". The first check of a unit, every
check on a unit that has not failed, the `tier1` node and the checks that gate review and push are full. The check that
follows a failed check and a fixer's commit is the **selected run**:

1. lint runs as it does today, in full (it is diff-scoped already and cheap); then the selected test commands.
2. If anything fails, the output is saved as feedback and the unit goes back to the fixer. The full suite does not run.
   This counts as a fix round against `max_check_rounds` exactly as a full failure does.
3. If everything passes, the full suite runs once. A pass there is the unit's green, and the graph moves to review. A
   failure there is a **disagreement**: the selection missed a test the change affects. It is counted, its output is the
   feedback, and the unit goes back to the fixer. The next round's check is a selected run again.
4. The selected run is a step in front of the full check, not a replacement: the unit is never green until a full run
   has passed on the current head, and the check cache (keyed by patch identity) only ever records full results.

The full suite remains mandatory before review and before every push. A selected run that passes does not skip anything
that a person or a later gate reads as "tier 1 passed".

If the selected command cannot be run (the plugin is not installed, the command is not found, its seed data is
unusable), the pipeline runs the full suite instead and records the reason; a broken selector costs time, never
correctness.

## The Python profile

Two tiers, chosen in order.

*Coverage-based selection* with a plugin of the testmon kind: it records, for each test, the source it executed, and
re-runs a test only when that source changed. The seed data lives in the unit's worktree and is created by the first
full run, so the first full run in a unit must be run with the plugin recording. The test environments here are created
per workspace member with an isolated environment, so the plugin is added to those runs, not assumed to be present.

*Fallback needing no plugin*: run the failed test identifiers that the failed output carries, using the identifier
reader that `flaky-tests` adds to the profile, first and alone. This makes a fix round's first look a few seconds. It
selects nothing the failure did not name, so it relies entirely on the confirming full run, and is therefore what a
repo gets when the plugin is absent or its seed data is missing.

If the profile's reader finds no identifiers (a lint failure, a collection error), the selected run is the full suite.

## Measurement

Each selected run writes one line to the usage ledger (the spans use the same writer, `record_line`) with the unit, the
node, the round, the selected count and the total, the estimated seconds saved, and the outcome of the confirming run
(`agreed`, `disagreed` or `not_run` when the selected run failed). The saving is an estimate: the duration of the last
full run on the unit minus the selected run's duration, never negative, and absent when the unit has no full run to
compare with. A line that cannot be written is dropped and the run goes on, as with the other ledger lines. Showing the
figures in a report is left to the change that adds the timeline to `abk report`; the lines carry what it needs.

## Unverified

- That a testmon-style plugin records and selects correctly under the parallel workers (`-n auto`) the Python profile
  uses. The plugin documents support for them; it has not been run against this pipeline's test suite.
- How much the selection saves. Most tests in the framework's own suite go through the wiring module and the graph
  driver, so a change there is expected to select nearly everything; the saving is expected mainly for edits to a leaf
  module. No measurement exists, which is why the mode is off by default and the measurement is part of the change.
- That the plugin's seed data survives a restack or a resumed run. The worktree is kept across a resume, but a rebuilt
  worktree loses the data and the next selected run falls back, which is safe and is covered by the full-suite fallback.
- That the identifier reader that `flaky-tests` adds will have the shape this change needs (a list of identifiers from
  the failed output). That change is not built yet.

## Not done

No test reorganisation: the test tree already mirrors the source folders, and selection by folder is not used. The
Node profile is not implemented here. Selection is not used at the pre-review gate or the push gate.
