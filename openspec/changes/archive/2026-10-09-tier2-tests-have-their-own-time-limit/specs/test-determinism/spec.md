## ADDED Requirements

### Requirement: A tier-2 test runs under its own time limit

A test that carries the tier-2 marker SHALL run under a time limit of its own, thirty minutes by default and set by its own option, with zero
turning it off, on each of its setup, call and teardown; every other test SHALL keep the limit it has. A failure from either limit SHALL
name the limit that was passed and say which kind it was. The limit on a tier-2 test SHALL NOT change the pipeline's tier-2 command, its
environment or the result it posts.

#### Scenario: A live test that takes minutes

- **GIVEN** a test with the tier-2 marker that runs for five minutes
- **WHEN** it runs under the default limits
- **THEN** it is not failed by the limit

#### Scenario: A module fixture that runs a tick

- **GIVEN** a module-scoped fixture of tier-2 tests that takes five minutes in its setup
- **WHEN** the first of those tests starts
- **THEN** its setup is not failed by the fast limit

#### Scenario: A tier-2 test that hangs

- **GIVEN** a tier-2 test that does not return
- **WHEN** the tier-2 limit passes
- **THEN** it fails with a message naming the tier-2 limit and its length

#### Scenario: A fast test is unchanged

- **GIVEN** a test without the tier-2 marker that does not return
- **WHEN** the fast limit passes
- **THEN** it fails with the message it had before

#### Scenario: The limit turned off

- **WHEN** the tier-2 limit is set to zero
- **THEN** a tier-2 test is not limited and the fast limit is as before
