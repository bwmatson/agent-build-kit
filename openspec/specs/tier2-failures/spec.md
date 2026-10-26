# tier2-failures Specification

## Purpose
TBD - created by archiving change tier2-waits-on-open-base-failure-fixes. Update Purpose after archive.

## Requirements

### Requirement: A unit about to run a full e2e-test run waits while a fix for a base failure is open

Before a unit makes a full-scope e2e-test run, one that executes the whole marker of its repo, the pipeline SHALL look in the record of failures that also fail on the base for a fix change that is still open
and was recorded for the unit's repo. For each such fix change the unit SHALL be given a `Needs:` line on it, through the same function the
unit that met the failure uses, and SHALL be parked, planned and gated, to resume through the existing wait-ends path. The check SHALL come
before the stack lock is taken and before any test, including the dev-stack script, runs. A unit that is not held SHALL run e2e-test as before. A run that is not full-scope SHALL NOT be held (next requirement).

#### Scenario: A second unit reaches e2e-test while a fix is open

- **GIVEN** a recorded base failure whose fix change is open, and another unit of the same repo about to run e2e-test
- **WHEN** the unit reaches the e2e-test step
- **THEN** its groups gain a `Needs:` line on the fix change, it is parked planned and gated, no test runs and the stack lock is not taken

#### Scenario: The parked unit frees its place and shows the wait

- **GIVEN** a unit parked at the gate
- **WHEN** the status is read
- **THEN** it is listed as waiting on the fix change and it holds no place against the unit limit

#### Scenario: The fix change is in review or merged

- **GIVEN** a unit parked at the gate and the fix change's unit now in review in the same repo, or merged
- **WHEN** the pass runs
- **THEN** the unit resumes, restacked onto the fix, runs e2e-test, and is not parked again because it already waits on that fix

#### Scenario: A unit that has not reached e2e-test yet

- **GIVEN** a unit still building when a base failure is recorded
- **WHEN** it later reaches e2e-test
- **THEN** it is held by the same gate and nothing was changed on it when the record was written

#### Scenario: The fix was merged and archived

- **GIVEN** a recorded base failure whose fix change is merged and archived
- **WHEN** a unit reaches e2e-test
- **THEN** it runs e2e-test and gains no `Needs:` line

#### Scenario: The gate writes nothing

- **WHEN** a unit is parked at the gate
- **THEN** no fix change is written, and the step reports `exists: <change>`

#### Scenario: E2e-test after a restack

- **GIVEN** a unit that is restacked onto a moved base and so runs e2e-test again, while a fix change is open that it does not wait on
- **WHEN** it reaches the e2e-test step
- **THEN** it is held by the gate like any other

### Requirement: Only a full-scope run is held

The gate SHALL hold only a run that executes the whole marker: the repo's `e2e_unit_scope` at `full`, a run through the repo's dev stack
script, and a run that could not be narrowed to the unit's own tests. It SHALL learn the scope from the one function the e2e-test step uses to decide
it, before any record is read. A run of the tests the unit added or changed, and a unit that runs no e2e-test test, SHALL NOT be held, given no `Needs:`
line and not parked, whatever fix changes are open.

#### Scenario: An own-scope run is not gated

- **GIVEN** `e2e_unit_scope` at `own` for the repo, an open fix change for a recorded base failure in the unit's repo, and a unit that added an e2e-test test
- **WHEN** the unit reaches the e2e-test step
- **THEN** it runs its own tests, gains no `Needs:` line, is not parked, and the record is not read

#### Scenario: A unit with no e2e-test test of its own

- **GIVEN** `own`, an open fix change in the unit's repo, and a unit that added or changed no e2e-test test
- **WHEN** it reaches the e2e-test step
- **THEN** it is not held, runs nothing, and takes no lock

#### Scenario: A full-scope run is gated

- **GIVEN** `e2e_unit_scope` at `full` for the repo and an open fix change in the unit's repo
- **WHEN** a unit reaches the e2e-test step
- **THEN** it is held as the first requirement says

#### Scenario: A run that could not be narrowed is gated

- **GIVEN** `own`, an open fix change in the unit's repo, and a repo that runs e2e-test through its dev stack script
- **WHEN** a unit reaches the e2e-test step
- **THEN** it is held, because the run executes the whole marker

### Requirement: The gate has bounded exemptions and a bounded scope

The gate SHALL NOT hold a unit of the fix change itself or a unit that already waits on it. A unit SHALL be exempt only from the fix change
that its own change is, or that it already waits on, and SHALL be held by any other open fix change recorded for its repo. A record SHALL hold
only the units of the repo whose suite holds the failing test.

#### Scenario: The fix change's own unit

- **GIVEN** an open fix change for a base failure
- **WHEN** a unit of that fix change reaches e2e-test
- **THEN** it runs e2e-test and gains no `Needs:` line

#### Scenario: A unit already waiting on the fix

- **GIVEN** a unit with a `Needs:` line on the open fix change
- **WHEN** it reaches e2e-test
- **THEN** it runs e2e-test and is not parked again

#### Scenario: A unit of one fix with another fix open

- **GIVEN** open fix changes A and B for two base failures of one repo
- **WHEN** a unit of fix A reaches e2e-test
- **THEN** it is held by fix B and gains a `Needs:` line on B only

#### Scenario: Another repo

- **GIVEN** an open fix change for a base failure in one repo
- **WHEN** a unit of a different repo reaches e2e-test
- **THEN** it runs e2e-test and gains no `Needs:` line

### Requirement: Only a failure that also fails on the base holds units

Only a record written by the classification of a failure that also fails on the base SHALL hold a unit. A unit's own failure and a flaky test
SHALL write no such record and SHALL hold no other unit. The gate SHALL add no path from an outage to a `Needs:` line, and a run already in
flight when a record is written SHALL finish and be classified as before. With `limits.e2e_base_runs` at zero nothing SHALL be recorded and
the gate SHALL hold no unit.

#### Scenario: A unit's own failure

- **GIVEN** a unit whose e2e-test failure is in a test it added or changed
- **WHEN** the next unit of the repo reaches e2e-test
- **THEN** it runs e2e-test

#### Scenario: A flake

- **GIVEN** a flaky test recorded with an open flake fix change
- **WHEN** a unit reaches e2e-test
- **THEN** it runs e2e-test and gains no `Needs:` line

#### Scenario: An outage

- **GIVEN** an e2e-test run that failed because the environment could not run it
- **WHEN** the next unit reaches e2e-test
- **THEN** no record exists from it and the unit is not held

#### Scenario: A run in flight

- **GIVEN** a unit already running e2e-test when another unit's failure is recorded
- **WHEN** its run ends
- **THEN** it is classified and judged as before, and no `Needs:` line is added by the gate

#### Scenario: The base run is off

- **GIVEN** `limits.e2e_base_runs` at zero
- **WHEN** a unit's e2e-test fails
- **THEN** nothing is recorded and no later unit is held

### Requirement: An abandoned fix change is left to the rule for a closed prerequisite

When a fix change a unit waits on at the gate is abandoned without merging, the unit SHALL be treated as any unit waiting on a closed
prerequisite is: the gate SHALL add no rule, no release and no command for it.

#### Scenario: The fix change is closed unmerged

- **GIVEN** a unit parked at the gate whose fix change's units are closed
- **WHEN** the pass runs
- **THEN** the unit stays waiting, listed with what it waits on, and nothing releases it until a person clears the wait the existing way

### Requirement: The status counts the units waiting on each fix

Each `pre-existing:` line of the status SHALL say how many units wait on that line's fix change when the count is above zero. The units that
wait SHALL be shown by the existing waiting display.

#### Scenario: Units wait on a fix

- **GIVEN** a recorded base failure with an open fix change and three units waiting on it
- **WHEN** the status is read
- **THEN** its `pre-existing:` line ends with `3 units waiting`

#### Scenario: Nothing waits

- **GIVEN** a recorded base failure with an open fix change and no unit waiting on it
- **WHEN** the status is read
- **THEN** the line is as before
