# Proposal

## Why

The pipeline runs some checks with its own interpreter: the changelog check is run by the process that runs
the tick, against a unit's branch. When the framework gained new dependencies, the pipeline's environment was
not brought up to date, so that check failed for every unit, whatever its branch held. Each unit's agent
found that the branch was fine and the environment was not, changed nothing, and the check-fix loop gave up:
the unit failed after spending agent rounds, and three units were lost until a person synced the environment
and requeued them.

Nothing in the pipeline looks after its own environment, and a failure that is the environment's fault is
indistinguishable from the unit's.

## What Changes

- **An `environment` section in configuration:** a required `sync` command, a required `check` command, and
  `inputs` in three parts (dependency manifests, lock files, anything else) whose contents decide when a sync
  is needed. The framework knows no package manager and no lock file name; behaviour is the commands and
  lists the section holds.
- **The tick keeps the environment current:** after finding there is work, and before starting any, it
  compares the inputs with what was last synced, runs `sync` when they changed, runs `check`, and when `check`
  fails runs `sync` once more and checks again. If it still fails the pass starts nothing and says why.
- **Init prepopulates it when it can:** `abk init` looks at the planning repository and writes the section,
  including the lock files it finds; where it cannot tell it writes empty required commands and says to
  set them. Re-running init fills the section when it is missing. `abk doctor` checks the section and runs
  `check`.
- **An `environment` cause:** a unit whose unit-test cannot run because the environment is unhealthy fails with
  that cause before any agent round is spent, keeps its build slot, and is resumed by the pass once the
  environment is healthy. A unit's own failure is never given this cause.
- **Code repositories can declare their own environment:** the same section under a repository, run in the
  unit's worktree before its tests and unit-test whenever its inputs changed there. A unit that adds a
  dependency has it synced before its next unit-test. A failing sync caused by inputs the unit changed is the
  unit's failure; any other failing sync or check is the environment's and gets the `environment` cause.
- **Lock files are left out of unit size from the same list:** the lock files named in the environment's
  inputs are not counted in a unit's size. The built-in list of lock file names is removed, so the framework
  carries no such list, and init writes the detected names.

## Impact

- agent-build-kit: configuration, `abk init`, `abk doctor`, the tick, the checks and unit-test nodes, the cause
  set, `abk status`, and the unit-size calculation.
- An installation relying on the built-in lock file names must run init's fill step, or list them, to keep
  them out of unit size.
