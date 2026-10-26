# Tasks

Acceptance: none — commands are faked at the argv boundary and the state is the unit store; tier-1 tests
prove it.

## 1. [agent-build-kit] [unit-test] The environment section, init and unit size

Priority: 2

Done when configuration describes the environment by commands and lists, init writes it where it can, and
lock files named there are left out of unit size.

- [x] 1.1 Test: a section with `sync`, `check` and inputs loads; one with an empty or missing `sync` or
      `check` fails naming the field; no section loads and `abk doctor` warns that none is managed.
- [x] 1.2 Test: `abk doctor` reports a listed input that does not exist and runs `check`.
- [x] 1.3 Test: init over a planning repository with a manifest, a lock file and a path-source checkout
      writes a sync command, a check, the manifests and lock files found, and the dry run shows them; over
      one it does not recognise it writes empty commands and says to set them; over a configuration with the
      section it changes nothing; over one without it, it fills only the missing parts.
- [x] 1.4 Test: a lock file named only in `environment.inputs.lock` is not counted in a unit's size; with
      no generated-file patterns and no environment a changed lock file is counted; init writes the lock
      files it detects into the patterns.
- [x] 1.5 Test: a repository entry accepts the same section with the same validation, init writes it from
      the files it finds in that repository, and `abk doctor` warns for a repository without one.
- [x] 1.6 Add the `environment` model and its validation, init's detection and fill-when-absent merge, the
      doctor checks, and the generated-file list as the explicit patterns plus the environment's lock list
      with the built-in names removed.
- [x] 1.7 Update `docs/configuration.md` and `docs/init.md`, and add a changelog entry that says an
      installation relying on the built-in lock file names must run init's fill step.

## 2. [agent-build-kit] [unit-test] The tick keeps the environment current

Priority: 2

Done when the tick syncs on a changed input, checks, heals once, and stops cleanly when the environment is
unhealthy.

- [x] 2.1 Test: a changed input runs `sync`, records the hash and runs `check` before any unit starts;
      unchanged inputs and a passing check run no `sync`; an idle tick runs neither.
- [x] 2.2 Test: a failing check with unchanged inputs runs `sync` once and checks again; a pass continues
      the pass; a second failure starts no unit, runs no unit-test, records the environment as unhealthy with
      the output, and exits non-zero.
- [x] 2.3 Test: `abk status` prints the environment state, and `abk doctor` runs the same check.
- [x] 2.4 Add `ensure_environment` after the work check and before the first round, the state record, the
      status line and the exit code.
- [x] 2.5 Document the step in `docs/architecture.md` and the pipeline skill, and add a changelog entry.

## 3. [agent-build-kit] [unit-test] The environment cause

Needs: flaky-tests group 1 merged — both edit the unit-test command assembly and the failure it returns, and the command limit bounds a pre-flight that hangs

Done when a unit blocked by the environment fails with its own cause before any agent runs, keeps its
slot, and resumes when the environment is healthy.

- [x] 3.1 Test: with a failing check a unit reaching unit-test is failed with the cause `environment`, runs
      no agent and saves no feedback; a failing pipeline-run command with a failing check does the same
      and spends no fix round; the cause set test lists the new cause.
- [x] 3.2 Test: a unit's own import error with a passing check is an ordinary unit-test failure that goes to
      the fix round.
- [x] 3.3 Test: such a unit still counts toward the units in progress, and the status command and the queue
      line name it as waiting for the environment.
- [x] 3.4 Test: after a healthy check the pass resumes these units from where they stopped within the
      concurrency limit and logs that the environment was restored; one that meets a failing check again
      returns to the cause without an agent run.
- [x] 3.5 Test: a store whose only unit that needs attention is failed with the cause `environment` counts as work, so
      a tick runs and resumes it; a unit failed for any other cause alone does not.
- [x] 3.6 Add the cause, the pre-flight and fault classification in the checks and unit-test nodes, the
      auto-resume in the pass, the check for work counting a unit failed with this cause, and the status and queue
      output.
- [x] 3.7 Update `docs/unit-graph.md` and the pipeline skill, and add a changelog entry.

## 4. [agent-build-kit] [unit-test] A code repository's environment in the unit's worktree

Needs: flaky-tests group 1 merged — both edit the unit-test command assembly and the failure it returns

Done when a unit's worktree is synced before its tests and unit-test whenever its inputs changed there, and a
failure is the unit's or the environment's according to who changed the inputs.

- [x] 4.1 Test: a unit that edits a manifest has `sync` run in its worktree before its next unit-test and the
      hash recorded for that worktree; unchanged inputs run no `sync`; a fresh worktree of a stacked unit
      runs `sync` before the tests node.
- [x] 4.2 Test: with inputs equal to the base branch's, a failing `sync` or `check` fails the unit with the
      cause `environment` before any agent round and it resumes when a later check passes.
- [x] 4.3 Test: with a manifest the unit's branch changed, a failing `sync` is an ordinary unit-test failure
      whose feedback is the sync output, and the cause is not `environment`.
- [x] 4.4 Test: a repository without the section syncs and checks nothing.
- [x] 4.5 Add the per-worktree record, the pre-flight in the tests node and before unit-test, and the
      attribution of a failing sync by comparing the inputs with the base branch's.
- [x] 4.6 Document the repository section in `docs/configuration.md` and `docs/architecture.md`, and add a
      changelog entry.
