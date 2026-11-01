# flake-handling Specification

## Purpose
TBD - created by archiving change flaky-tests. Update Purpose after archive.

## Requirements

### Requirement: A failed test is rerun alone to tell a flake from a failure

When unit-test fails on tests, the pipeline SHALL run the failed tests again, serially, twice, using the profile's hooks to
read their identifiers and build the command. A test that fails again SHALL be a real failure and the unit SHALL fail as
before. A test that passes both times SHALL be a flake. A profile without the hooks SHALL behave as before.

#### Scenario: A test that fails again

- **GIVEN** a failed test that fails on the serial rerun
- **WHEN** unit-test is judged
- **THEN** the unit fails as it does today

#### Scenario: A test that passes alone

- **GIVEN** a failed test that passes both serial reruns
- **WHEN** unit-test is judged
- **THEN** it is a flake and the unit does not fail for it

#### Scenario: No hooks

- **GIVEN** a profile that offers no hooks
- **WHEN** unit-test fails
- **THEN** the unit fails as it does today

### Requirement: A flake is recorded

A flake SHALL be appended to a record with the test, the unit, the command, the first failure's output and the time, and
the status command SHALL list each flaky test with the number of times it flaked and the change that fixes it.

#### Scenario: A flake is recorded

- **WHEN** a flake is found
- **THEN** the record gains an entry and the status command lists the test

### Requirement: One fix change per flaky test is written and every blocked unit waits on it

For a flaky test the pipeline SHALL write, without a model, one change that makes it deterministic, named from the test's
identifier, with a proposal giving the test, how it failed, that it passed alone, its history and the production module it
exercises, a design stub asking whether the test or the code is racy, and a group, tests first, that reproduces the race
deterministically, makes the test pass and runs it under the repeat check. Making sure the change exists SHALL be one step
taken under a lock. Every unit that meets that flake SHALL wait on that one change through a `Needs:` line and no second
change SHALL be written for it while the first is unmerged.

#### Scenario: The first unit to meet a flake

- **WHEN** a unit meets a flake for which there is no open change
- **THEN** the change is written, the unit's group gains a `Needs:` line on it, and the unit is parked gated

#### Scenario: Two units meet the same flake in one tick

- **WHEN** two units meet the same flake
- **THEN** one change is written and both units wait on it

#### Scenario: A later unit meets it

- **GIVEN** an open fix change for the test
- **WHEN** another unit meets the flake
- **THEN** it gains a `Needs:` line on the same change and none is written

#### Scenario: The fix has merged and the test flakes again

- **GIVEN** a fix change merged and archived
- **WHEN** the test flakes again
- **THEN** a successor is written naming the earlier attempt, and units still waiting wait on the successor

#### Scenario: The fix change itself

- **GIVEN** a unit of the fix change that meets the flake
- **WHEN** unit-test is judged
- **THEN** it does not wait on its own change

### Requirement: A unit that waited resumes at unit-test when the fix merges

A unit parked for a flake SHALL resume at unit-test, restacked, when the fix change has merged, and the check that sends a
unit back when unit-test fails on the base SHALL NOT apply to a flake.

#### Scenario: The fix merges

- **GIVEN** a unit gated on a fix change
- **WHEN** the fix merges
- **THEN** the unit is released, restacked and runs unit-test again

#### Scenario: A flake on the base

- **GIVEN** unit-test failing on the base only through a flaky test
- **WHEN** it is judged
- **THEN** the unit is not sent back as having a moved base
