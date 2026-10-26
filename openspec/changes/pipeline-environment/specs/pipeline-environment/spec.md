## ADDED Requirements

### Requirement: The environment is described by commands and file lists

Configuration SHALL accept an `environment` section with a required `sync` command, a required `check`
command and `inputs` in three lists: dependencies, lock files and other files. A present section with a
missing or empty `sync` or `check` SHALL be a configuration error. The framework SHALL NOT branch on a
package manager, a language or a lock file name. A configuration without the section SHALL manage no
environment, and `abk doctor` SHALL warn.

#### Scenario: A complete section

- **WHEN** a configuration has `sync`, `check` and inputs
- **THEN** it loads, and the pipeline uses exactly those commands and files

#### Scenario: An empty command

- **GIVEN** a section whose `check` is empty
- **WHEN** the configuration is loaded
- **THEN** loading fails naming `environment.check`

#### Scenario: No section

- **WHEN** a configuration has no `environment` section
- **THEN** the pipeline syncs and checks nothing, and `abk doctor` warns that none is managed

### Requirement: The tick keeps the environment current before it starts work

After finding there is work and before starting any, the tick SHALL compare a hash of the inputs' contents
with the one last recorded, SHALL run `sync` and record the new hash when they differ or none is recorded,
SHALL run `check`, and when `check` fails SHALL run `sync` once more and check again. When it still fails
the tick SHALL start no work, SHALL record the environment as unhealthy with the output, and SHALL exit
non-zero. A tick with no work SHALL do none of this.

#### Scenario: An input changed

- **GIVEN** a dependency manifest that changed since the last sync
- **WHEN** the tick runs
- **THEN** `sync` runs, the hash is recorded, and `check` runs before any unit starts

#### Scenario: Nothing changed and the check passes

- **WHEN** the inputs are unchanged and `check` passes
- **THEN** `sync` does not run

#### Scenario: The check fails with unchanged inputs

- **GIVEN** unchanged inputs and a failing `check`
- **WHEN** the tick runs
- **THEN** `sync` runs once and `check` runs again, and a pass means the pass continues

#### Scenario: Still unhealthy

- **WHEN** `check` still fails after the second sync
- **THEN** no unit is started, no unit-test runs, the output is printed, the environment is recorded as
  unhealthy, and the tick exits non-zero

#### Scenario: An idle tick

- **WHEN** there is no work
- **THEN** neither `sync` nor `check` runs

### Requirement: Init prepopulates the environment section when it can

`abk init` SHALL write an `environment` section from what it finds in the planning repository, including
the lock files and the manifests of checkouts the manifests name, and SHALL write empty required commands
with a message when it recognises nothing. On an existing configuration it SHALL fill the section when it
is missing, SHALL show it in a dry run, and SHALL NOT change a section already present. `abk doctor` SHALL
verify that every listed input exists and SHALL run `check`.

#### Scenario: A recognised layout

- **GIVEN** a planning repository with a manifest and its lock file
- **WHEN** `abk init` runs
- **THEN** the section names a sync command, a check and the files found, and the dry run shows them

#### Scenario: Nothing recognised

- **WHEN** init finds nothing it recognises
- **THEN** the section is written with empty `sync` and `check`, and init says to set them by hand

#### Scenario: A section already present

- **WHEN** init runs on a configuration that has an `environment` section
- **THEN** the section is unchanged

#### Scenario: A missing input

- **GIVEN** an input path that does not exist
- **WHEN** `abk doctor` runs
- **THEN** it reports that input

### Requirement: A failure caused by the environment is its own cause and keeps its slot

Before a unit's unit-test runs, and again when a command the pipeline itself runs for unit-test fails, the
pipeline SHALL run `check`. When `check` fails, the unit SHALL be set to failed with the cause
`environment`, no feedback SHALL be saved, no fix round SHALL run, and the unit SHALL continue to count
toward the units in progress. A failure of the unit's own commands while `check` passes SHALL be an
ordinary failure.

#### Scenario: A broken environment before unit-test

- **GIVEN** a failing `check`
- **WHEN** a unit reaches its unit-test
- **THEN** it is failed with the cause `environment`, no agent runs, and it holds its place

#### Scenario: A pipeline-run command fails

- **GIVEN** a command the pipeline runs for unit-test that fails, and a `check` that fails at that moment
- **WHEN** the unit's checks run
- **THEN** the unit is failed with the cause `environment` and no fix round is spent

#### Scenario: A unit's own import error

- **GIVEN** a unit whose own code fails to import, and a passing `check`
- **WHEN** its unit-test runs
- **THEN** the failure is an ordinary unit-test failure and goes to the fix round

#### Scenario: The queue

- **GIVEN** units failed with the cause `environment`
- **WHEN** the status command is read
- **THEN** they are counted among the units in progress and named as waiting for the environment

### Requirement: Units that waited for the environment resume when it is healthy

Each tick, after the environment is found healthy, units failed with the cause `environment` SHALL be
resumed from the node they stopped at, as `abk requeue` resumes a unit, within the concurrency limits. When
the environment breaks again they SHALL return to the cause without an agent run.

#### Scenario: The environment is repaired

- **GIVEN** units failed with the cause `environment`
- **WHEN** a tick finds the environment healthy
- **THEN** they are resumed from where they stopped and the log says the environment was restored

#### Scenario: Broken again

- **WHEN** a resumed unit meets a failing `check` at its pre-flight
- **THEN** it returns to the cause `environment` and no agent runs

#### Scenario: Only environment-failed units remain

- **GIVEN** no unit being built, waiting or in review, and one unit failed with the cause `environment`
- **WHEN** the pipeline decides whether a tick has work
- **THEN** it has work, so the tick checks the environment and resumes the unit when it is healthy

#### Scenario: A unit failed for another cause

- **GIVEN** no unit being built, waiting or in review, and one unit failed with an ordinary cause
- **WHEN** the pipeline decides whether a tick has work
- **THEN** it has none, as before

#### Scenario: More units than the limit

- **GIVEN** more units waiting than the concurrency limit allows
- **WHEN** the environment is healthy
- **THEN** no more than the limit run at once

### Requirement: A code repository can declare its own environment

A repository entry SHALL accept the same `environment` section as the planning repository, with the same
required commands and input lists relative to the repository. In the unit's worktree, before the tests
node and before every unit-test, the pipeline SHALL hash the repository's inputs there, SHALL run `sync` when
the hash differs from the one recorded for that worktree or none is recorded, and SHALL then run `check`.
When the inputs equal the base branch's, a failing `sync` or `check` SHALL give the unit the cause
`environment`; when the unit's branch changed the inputs, a failing `sync` SHALL be an ordinary unit-test
failure whose feedback is the sync output.

#### Scenario: A unit adds a dependency

- **GIVEN** a unit that edits a repository's dependency manifest
- **WHEN** its next unit-test is about to run
- **THEN** `sync` runs in its worktree first, and the new hash is recorded for that worktree

#### Scenario: A stacked unit

- **GIVEN** a unit stacked on one that added a dependency, in a fresh worktree
- **WHEN** its tests node starts
- **THEN** `sync` runs in the worktree because none is recorded, and `check` passes before the agent runs

#### Scenario: The environment is broken, not the unit

- **GIVEN** inputs equal to the base branch's and a failing `check`
- **WHEN** the unit's unit-test is about to run
- **THEN** the unit is failed with the cause `environment` and no agent runs

#### Scenario: The unit's own manifest is unsatisfiable

- **GIVEN** a unit whose branch changed a manifest so that `sync` fails
- **WHEN** its unit-test is about to run
- **THEN** the failure goes to the fix round with the sync output as feedback, and the cause is not `environment`

#### Scenario: A repository without the section

- **WHEN** a repository has no `environment` section
- **THEN** nothing is synced or checked for it and `abk doctor` warns

### Requirement: Lock files named in the environment are left out of a unit's size

The files left out of a unit's size SHALL be the configured generated-file patterns together with the lock
files of the planning environment and of every repository's environment, and the framework SHALL carry no built-in list of lock file names. `abk init`
SHALL write the lock files it detects into the generated-file patterns and into the environment's lock
list.

#### Scenario: A lock file named only in the environment

- **GIVEN** a lock file listed only in `environment.inputs.lock`
- **WHEN** a unit's size is measured
- **THEN** its lines are not counted

#### Scenario: No built-in names

- **GIVEN** a configuration that names no generated files and no environment
- **WHEN** a unit that changes a lock file is measured
- **THEN** the lock file's lines are counted

#### Scenario: Init writes the names

- **WHEN** `abk init` finds lock files in a repository
- **THEN** their names are written into the generated-file patterns
