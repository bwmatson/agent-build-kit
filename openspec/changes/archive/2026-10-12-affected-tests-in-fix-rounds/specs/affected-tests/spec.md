## ADDED Requirements

### Requirement: A toolchain profile can name the tests a change affects

A toolchain profile SHALL be able to return, for the files a branch changes and the identifiers of the tests that
failed, the commands that run the tests the change affects, or nothing when it cannot say. A profile that does not
implement the hook SHALL behave as one that returns nothing.

#### Scenario: A profile that cannot say

- **GIVEN** a profile with no selection
- **WHEN** a selected run is asked for
- **THEN** the full suite runs and the run log says why

#### Scenario: A profile that nothing is affected for

- **GIVEN** a profile that returns an empty list of commands
- **WHEN** the selected run is made
- **THEN** it counts as a selected run that passed with no tests, and the full suite still confirms

### Requirement: A repo chooses how a fix round selects tests

A repo's configuration SHALL set `checks.affected.mode` to `off`, `profile` or `command`, defaulting to `off`. In
`command` mode it SHALL give a template in which `{changed_files}` and `{failed_ids}` are replaced by separate quoted
arguments. A `command` mode without a template SHALL be rejected when the configuration loads.

#### Scenario: Off is today's behaviour

- **GIVEN** a repo that sets no mode
- **WHEN** a check fails and the fixer commits
- **THEN** the next check runs the full tests

#### Scenario: Command mode

- **GIVEN** `command` mode with a template using both placeholders
- **WHEN** a fix round's selected run is made
- **THEN** each placeholder is replaced by the changed files and the failed identifiers as separate arguments

### Requirement: A fix round runs the selected tests, and the full suite confirms a pass

After a failed check and a fixer's commit, with the mode on, the next check SHALL run lint in full and the selected
tests. If the selected run fails, the unit SHALL return to the fixer and the full suite SHALL NOT run. If it passes, the
full suite SHALL run once. A selected run SHALL NOT make a unit green; only a full run on the current head SHALL.

#### Scenario: The selected run fails

- **GIVEN** the mode is on and a fix has been committed
- **WHEN** the selected run fails
- **THEN** its output goes to the fixer and the full suite does not run

#### Scenario: Selected pass, full pass

- **WHEN** the selected run passes and the full suite then passes
- **THEN** the unit proceeds to review

#### Scenario: Selected pass, full failure

- **WHEN** the selected run passes and the full suite fails
- **THEN** it is counted as a disagreement and the full output goes to the fixer

### Requirement: The full suite is mandatory at every gate

The full suite SHALL run before review and before every push, for a unit that has not failed a check, for the first
check, and in the `tier1` run for a unit that produced nothing or was moved onto a new base. Selection SHALL NOT be used
at any of them, and only full results SHALL be recorded in the check cache.

#### Scenario: A unit that never failed

- **GIVEN** the mode is on
- **WHEN** the first check of a unit runs
- **THEN** it runs the full suite

#### Scenario: A selector that cannot run

- **GIVEN** a selected command that cannot start
- **WHEN** the selected run is made
- **THEN** the full suite runs instead and the reason is recorded

### Requirement: The Python profile selects by coverage and falls back to the failed tests

The Python profile SHALL select tests by the source they execute, using seed data kept in the unit's worktree and
created by the first full run. Without usable seed data or the plugin it SHALL run the failed test identifiers first and
alone. With no identifiers it SHALL return nothing.

#### Scenario: No seed data

- **GIVEN** a worktree with no seed data and a failed test in the output
- **WHEN** the profile is asked
- **THEN** it returns the command that runs that test alone

#### Scenario: A lint failure

- **GIVEN** a failure that names no test
- **WHEN** the profile is asked
- **THEN** it returns nothing and the full suite runs

### Requirement: Each selected run is recorded

Each selected run SHALL write a ledger line with the unit, node and round, the number of tests selected and the total,
the estimated seconds saved, and the outcome of the confirming run (`agreed`, `disagreed` or `not_run`). The estimate
SHALL be absent when the unit has no full run to compare with and SHALL NOT be negative. A line that cannot be written
SHALL NOT fail the run.

#### Scenario: A disagreement is recorded

- **WHEN** a selected run passes and the full suite fails
- **THEN** the line reads `disagreed`

#### Scenario: An unwritable ledger

- **GIVEN** a ledger that cannot be written
- **WHEN** a selected run finishes
- **THEN** the run continues and the loss is reported once
