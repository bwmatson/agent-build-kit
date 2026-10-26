# stub-check-loop Specification

## Purpose
TBD - created by archiving change tests-are-stubbed-checked-and-committed-per-group. Update Purpose after archive.

## Requirements

### Requirement: The test step's work is checked before it is committed

In a stubbed build, after the test agent has written the stubs and tests of a group, the pipeline SHALL run the profile's lint,
format and type checks over what it wrote, including files it added, before the tests commit is made. It SHALL NOT run the tests: they
are meant to fail. The checks SHALL be the ones the push gate runs at the tests commit.

#### Scenario: Everything passes

- **WHEN** the stubs and tests pass lint, format and types
- **THEN** the tests commit is made and the implementation is written

#### Scenario: A new file

- **GIVEN** a stub in a file the agent added and did not stage
- **WHEN** the checks run
- **THEN** the file is checked

#### Scenario: The tests are not run

- **WHEN** the checks run
- **THEN** no test is executed

### Requirement: A failure goes back to the test agent and is kept as feedback

When a static check fails, the pipeline SHALL save the failing output as the unit's feedback with its own source, distinct from the
failure of the build's checks and of review, and SHALL give it to the test agent in the same worktree with a prompt that asks it to
make the existing stubs and tests pass the checks without changing what the tests assert or loosening a type or a rule, and then run
the checks again. A fix that changes nothing SHALL stop the unit.

#### Scenario: A lint failure

- **GIVEN** a test file with an unused import
- **WHEN** the checks fail
- **THEN** the test agent is shown the linter's output, removes the import, and the checks run again and pass

#### Scenario: A type failure in a stub

- **WHEN** the type check names a stub
- **THEN** the test agent is shown the checker's output and the stub is corrected, not suppressed

#### Scenario: A fix that changed nothing

- **WHEN** the test agent finishes a fix round with the tree as it was
- **THEN** the unit stops, naming the round, and the output stays on the unit

### Requirement: The loop is bounded by its own round counter

The loop SHALL repeat at most `global_limits.max_check_rounds` times, counted apart from the build's check rounds and begun again for
each group's tests. A unit still failing when the rounds are used SHALL stop, with the last output kept on the unit, before any
implementation is attempted and with no tests commit made for that group. `null` SHALL mean no limit and 0 SHALL stop at the first
failure.

#### Scenario: The rounds run out

- **GIVEN** `max_check_rounds: 2` and a stub that fails the type check after each fix
- **WHEN** the loop has made two fixes and the checks still fail
- **THEN** the unit stops, its feedback holds the last output, no tests commit exists for the group and the implementation is not written

#### Scenario: Counted apart

- **GIVEN** `max_check_rounds: 3`
- **WHEN** the loop used all three and a later group's tests are written
- **THEN** that group's loop has three rounds of its own

#### Scenario: Zero

- **GIVEN** `max_check_rounds: 0`
- **WHEN** a static check fails
- **THEN** the unit stops at once with no fix attempt

### Requirement: A unit stopped in the loop resumes in the loop

A unit whose saved feedback comes from this loop SHALL, when it is requeued, go back to the test step, which SHALL give the saved
output to the test agent first, and SHALL NOT go to rework. A fix round already made SHALL NOT be made again after a restart.

#### Scenario: Requeued after a stop

- **GIVEN** a unit stopped in the loop with its output saved
- **WHEN** it is requeued
- **THEN** the next agent call is a fix of that output, and review is not asked for

#### Scenario: Killed in a fix

- **WHEN** the run ends while the test agent is fixing
- **THEN** the run resumes at the fix with the rounds counted so far
