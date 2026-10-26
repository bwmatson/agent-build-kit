## ADDED Requirements

### Requirement: A failed e2e-test test is classified as the unit's own or untouched

When a unit's e2e-test run fails, the pipeline SHALL classify each failed test by its file. A test whose file the unit's branch added or changed
against its base SHALL be the unit's own, and a unit with a failure of its own SHALL fail as it does today. Every other failed test SHALL be
untouched. When the failed tests cannot be read, or the run was on the dev stack, nothing SHALL be classified and the unit SHALL fail as it does
today.

#### Scenario: A test the unit changed fails

- **GIVEN** an e2e-test failure in a test file the branch changed
- **WHEN** the failure is classified
- **THEN** the test is the unit's own, nothing is run on the base, and the unit fails as today

#### Scenario: A test in an untouched file fails

- **GIVEN** an e2e-test failure in a test file the branch did not change
- **WHEN** the failure is classified
- **THEN** the test is untouched and is run on the base

#### Scenario: A support file the unit changed

- **GIVEN** a branch that changed a `conftest.py` beside a failing test file it did not otherwise touch
- **WHEN** the failure is classified
- **THEN** the test is the unit's own

#### Scenario: The failed tests cannot be read

- **GIVEN** a failed e2e-test run whose output names no failed test, or a profile without the hook
- **WHEN** the failure is classified
- **THEN** nothing is classified, nothing is run on the base, and the unit fails as today

#### Scenario: The dev stack runs e2e-test

- **GIVEN** a repo whose e2e-test is its dev stack script
- **WHEN** the run fails
- **THEN** the unit fails as today and no base run is made

### Requirement: Untouched failed tests are run once on the base in a clean worktree

The pipeline SHALL run the untouched failed tests, together and once, on the ref the unit's e2e-test ran against, in a clean worktree that is
removed however the run ends, inside the hold on the live stack that the unit's own run took. A test SHALL be pre-existing only when the base run
names it as failed or errored. A test that passes on the base, is not collected there, or is not named by the base run SHALL be one the unit
broke, and a unit with such a failure SHALL fail as today and SHALL NOT be parked behind a fix. There SHALL be one base run, never repeated, and
a setting SHALL turn it off so that the unit fails as today.

#### Scenario: The test fails on the base too

- **GIVEN** an untouched test that fails on the unit's branch
- **WHEN** it is run on the base and fails there
- **THEN** it is pre-existing and charged to the base

#### Scenario: The test passes on the base

- **GIVEN** an untouched test that fails on the unit's branch
- **WHEN** it is run on the base and passes
- **THEN** the unit broke it, the unit fails as today, and it is not parked behind a fix

#### Scenario: The test does not exist on the base

- **GIVEN** a failed test the base does not contain
- **WHEN** the base run collects nothing for it
- **THEN** it is not pre-existing and the unit fails as today

#### Scenario: One run for every untouched test

- **GIVEN** three untouched failed tests
- **WHEN** the base run is made
- **THEN** one command runs the three, and it is not run again

#### Scenario: The worktree is clean and removed

- **GIVEN** a base run that raises
- **WHEN** it ends
- **THEN** its worktree is gone and the unit's own tree is unchanged

#### Scenario: The base run is on the stack the unit's run held

- **GIVEN** a unit that holds the live-stack lock for its e2e-test run
- **WHEN** the base run is made
- **THEN** it runs before the lock is released and does not take the lock again

#### Scenario: The base run turned off

- **WHEN** the setting that allows the base run is zero and an untouched test fails
- **THEN** no base run is made and the unit fails as today

#### Scenario: The setting cannot ask for more than one run

- **WHEN** the setting is given a value above one
- **THEN** the configuration is refused

#### Scenario: A failure of its own and a pre-existing one

- **GIVEN** a unit with one failed test of its own and one that fails on the base
- **WHEN** e2e-test is judged
- **THEN** the unit fails as today, the pre-existing failure is recorded with its fix change written, and the unit gains no `Needs:` line

### Requirement: E2e-test tests are not repeated or isolated

An e2e-test test SHALL be run by the e2e-test gate alone: the repeat of the tests a unit added or changed and the serial rerun that tells a flake from a
failure SHALL apply to the unit-test commands only, whatever the repeat setting.

#### Scenario: A failing e2e-test test with the repeat on

- **GIVEN** the repeat setting at three and an e2e-test command that fails
- **WHEN** the unit's e2e-test runs
- **THEN** the command runs once on the unit's tree

#### Scenario: An e2e-test command among the repeated tests

- **GIVEN** a unit that added an e2e-test test
- **WHEN** unit-test repeats the tests the unit added
- **THEN** no e2e-test command is among those run

### Requirement: A pre-existing failure is recorded and listed

Each pre-existing failure SHALL be appended to a record with the test, the unit, the command, the first failure line, the time and the base run's
result, and the status command SHALL list each such test with the number of times it failed on the base and the change that fixes it.

#### Scenario: A failure is recorded

- **WHEN** a test is found to fail on the base too
- **THEN** the record gains an entry with the fields named and the status command lists the test with its fix change

#### Scenario: The same test met twice

- **GIVEN** a recorded pre-existing failure
- **WHEN** another unit meets it
- **THEN** the status command lists it once with a count of two

### Requirement: One fix change per pre-existing failing test is written, previewed first

For each test that fails on the base the pipeline SHALL write, without a model, one change that makes it pass, named from the test's identifier,
with a proposal giving the test, its failure, the base run's result and the units that met it, a design stub, and an e2e-test group with its tests
first and an acceptance opt-out that says the test's own run is the check. Making sure the change exists SHALL be one step under a lock that
SHALL first look for an open change for that identifier and an archived earlier attempt, report `exists: <change>` or `would write: <change>`,
and only then write. No second change SHALL be written for an identifier while the first is open.

#### Scenario: No change exists

- **WHEN** a test is found to fail on the base and no change is open for it
- **THEN** `would write: <change>` is reported, the change is written, and it passes the validation of the change and of its tags

#### Scenario: A change is open

- **GIVEN** an open fix change for the test
- **WHEN** another unit meets the failure
- **THEN** `exists: <change>` is reported and nothing is written

#### Scenario: The fix merged and the test fails again

- **GIVEN** a fix change merged and archived
- **WHEN** the test fails on the base again
- **THEN** a successor is written naming the earlier attempt, and units still waiting wait on the successor

#### Scenario: A flaky test and a pre-existing failure

- **GIVEN** an open flake fix for a test
- **WHEN** the same test is found to fail on the base
- **THEN** a separate change of its own kind is written

### Requirement: The fix changes the pipeline writes are priority 1

A fix change the pipeline writes without a model, whether for a pre-existing failing test or for a flaky one, SHALL carry `Priority: 1` on its group, because
every unit blocked behind it waits until it merges.

#### Scenario: A pre-existing failure's fix

- **WHEN** the change for a pre-existing failing test is written
- **THEN** its group carries `Priority: 1`

#### Scenario: A flaky test's fix

- **WHEN** the change for a flaky test is written
- **THEN** its group carries `Priority: 1`, not the lower value earlier changes of this kind were written with

### Requirement: A dry-run tick previews the fix changes without writing

`abk tick --dry-run` SHALL print, for each recorded pre-existing failure, the same `exists: <change>` or `would write: <change>` line the ensure
step reports before it writes, and SHALL write no change, run no base run and start no unit.

#### Scenario: A recorded failure with an open change

- **GIVEN** a recorded pre-existing failure with an open change
- **WHEN** `abk tick --dry-run` runs
- **THEN** it prints `exists: <change>` and writes nothing

#### Scenario: A recorded failure with no open change

- **GIVEN** a recorded pre-existing failure whose earlier change was merged and archived
- **WHEN** `abk tick --dry-run` runs
- **THEN** it prints `would write: <successor>` and the planning directory is unchanged

### Requirement: A unit behind a fix waits on it and resumes at e2e-test

When every failure of a unit's e2e-test run is pre-existing, the unit SHALL be parked, gated, with a `Needs:` line on each fix change, and SHALL
resume at e2e-test when the fix changes have merged. Two units meeting one failure SHALL produce one change and two lines. The unit that builds the
fix change SHALL NOT wait on its own change.

#### Scenario: Every failure is pre-existing

- **GIVEN** an e2e-test run whose every failed test fails on the base
- **WHEN** e2e-test is judged
- **THEN** each group of the unit gains a `Needs:` line on the fix change and the unit is parked gated, not failed

#### Scenario: Two units meet one failure in one tick

- **WHEN** two units meet the same pre-existing failure
- **THEN** one change is written and both units gain a line on it

#### Scenario: The fix merges

- **GIVEN** a unit parked on a fix change
- **WHEN** the fix change's group merges
- **THEN** the unit is released, restacked, and e2e-test runs again in full

#### Scenario: The fix change's own unit

- **GIVEN** a unit of the fix change whose e2e-test run fails on the same test
- **WHEN** e2e-test is judged
- **THEN** it does not wait on its own change and fails as today

### Requirement: A failed unit's feedback does not carry untouched tests' output

The feedback saved when a unit fails e2e-test, and so every rework prompt made from it, SHALL hold the failures that are the unit's and SHALL NOT
hold the output of an untouched test that fails on the base, which SHALL be named once as recorded. When nothing was classified the feedback SHALL
be as before.

#### Scenario: A mixed failure

- **GIVEN** a failure of the unit's own test and an untouched test that fails on the base
- **WHEN** the feedback is saved
- **THEN** it holds the output of the unit's test and names the other only as recorded

#### Scenario: Nothing classified

- **GIVEN** a failure that could not be classified
- **WHEN** the feedback is saved
- **THEN** it is the text saved today

#### Scenario: A person's own words

- **GIVEN** feedback that a person wrote and an e2e-test failure with an untouched test
- **WHEN** the feedback is saved
- **THEN** the person's words stay and no untouched test's output is added to them
