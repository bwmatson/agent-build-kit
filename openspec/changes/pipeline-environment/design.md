# Design

## No built-in knowledge of tools

Nothing in the framework branches on a package manager, a language or a lock file name. The `environment`
section holds argv lists and path lists, like a deploy rule's command. A tool-specific default would be a
list that decides behaviour across an unbounded set of ecosystems, so there is none: if the section is
present, `sync` and `check` are required, and a present-but-empty command is a configuration error.

```
environment:
  sync:  <argv>   # brings the environment up to date, run in the planning repository
  check: <argv>   # exits 0 when the environment is healthy
  inputs:
    dependencies: [<path>, ...]
    lock: [<path>, ...]
    other: [<path>, ...]
```

If the section is absent the pipeline manages nothing and `abk doctor` warns. Paths are relative to the
planning repository and may point outside it, which is how a separately checked-out framework is watched.

## What init does

`abk init` is the only place that guesses. It looks at marker files in the planning repository and proposes
text to write: a sync command, the manifests and lock files it finds (including those of checkouts the
manifest names as sources), and a check that loads the framework with the interpreter that runs the
pipeline. These guesses live in init alone, as the detection of a code repository's tools already does, and
only choose what is written; once written, they are plain configuration that can be edited, and nothing
downstream reads them. Where nothing is recognised, init writes the section with empty commands and prints
that they must be set by hand. On an existing configuration, init fills `environment` and the generated-file
list when they are missing, and shows what it would write in a dry run.

## The tick

After the tick has found there is work, and before the first round, it:
1. hashes the contents of every input and compares the hash with the one recorded in the state directory;
2. runs `sync` when the hash differs or none is recorded, then records the new hash;
3. runs `check`; when that fails with an unchanged hash it runs `sync` once and checks again;
4. when `check` still fails, records the environment as unhealthy with the output and when it began, starts
   no new work, runs no unit-test, prints what failed and exits non-zero so the service shows as failed.

Idle ticks do none of this. `abk status` prints the environment's state and `abk doctor` runs `check`.

## The environment cause

Before a unit's unit-test runs, `check` is run, its result kept for the tick. When a command that the pipeline
itself runs for unit-test (a profile's own extra checks, the commit hooks, an executable that is not found)
fails, `check` is run again. If `check` fails in either case, the unit is set to failed with the cause
`environment` and a note, no feedback is saved and no fix round runs. A failure of the unit's own commands
with a passing `check` is an ordinary failure, so a unit's own import error is never taken for the
environment's.

A failed unit holds its build slot, as any failed unit does, and the cause is documented as deliberate:
the work is still owed and the slot is not given to new work while the environment cannot run it. The decision stays
`failed` rather than a parked `planned` unit: the unit keeps its place and is visible to a person, who can requeue it
by hand at any time. The pattern this sits beside is the code host being unavailable, which parks a unit with its own
cause, a backoff and a way back in the same pass; the environment cause differs in being resumed by the next tick's
health check, not by a timer.

Whether a tick runs at all is decided by the check for work, which counts only units being built, waiting or in review.
A unit failed with the cause `environment` alone would not make a tick run, so nothing would ever check the
environment or resume it. The check for work therefore also counts a unit that is failed with the cause `environment`.
Any other failed unit still waits for a person and does not keep ticks busy. While the environment stays broken each
tick finds the work, runs the health step, and exits non-zero without starting anything, as an unhealthy tick does.

The default runner of the unit-test command has no time limit, so a command that hangs on a broken environment would hold
the pre-flight forever; the command limit added by `flaky-tests` group 1 bounds it, and this change relies on that
rather than adding a second one.

Each tick, after the environment is found healthy, units that are failed with the cause `environment` are
resumed from the node they stopped at, by the path `abk requeue` uses. They are already counted in progress,
so the concurrency limits apply and nothing floods. If the environment breaks again they return to the
cause at the next pre-flight, without an agent run.

## Unit size

The files left out of a unit's size become the explicit list plus the environment's lock list. The default
list of lock file names is removed from configuration; init writes the lock files it detects in each
repository into the list, and into the environment's lock list for the planning repository.

## Code repositories have environments too

A repository the pipeline builds units for (the framework itself, a service stack, a platform repo) can need
the same thing, and the likeliest case is a unit that adds a dependency: its own later steps, and any unit
stacked on it, run in worktrees whose environment lacks the new package. A tool that prepares its environment
on every run hides this; one that does not shows it as a failure that is the environment's and not the code's.

A repository may carry the same `environment` section under its entry in `repos`, with the same required
`sync` and `check` and the same three input lists, relative to the repository. They run in the unit's
worktree. Before the tests node and before every unit-test, the pipeline hashes the repository's inputs in the
worktree and compares the hash with the one recorded for that worktree; when they differ, or none is
recorded, it runs `sync` there and records the hash, then runs `check`. Because the hash is of the
worktree's current files, a unit that edits a manifest has its environment synced again before its next
unit-test with nothing more to do.

Whose fault a failure is depends on whether the unit changed the inputs. When the inputs match the base
branch's, a failing `sync` or `check` is the environment's: the unit is failed with the cause `environment`,
as for the pipeline's own environment, and resumes when a later check passes. When the unit's own branch
changed the inputs, a failing `sync` is the unit's failure and goes to the fix round like any unit-test
failure, with the sync output as its feedback.

Init writes a repository's section from the files it finds there, exactly as for the planning repository.
The live or deployed environment of a service, including a native host install, is not covered here:
deploy rules own it.

## Decisions

- An unhealthy tick exits non-zero, so the service shows as failed and cannot go unnoticed.
