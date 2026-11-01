## ADDED Requirements

### Requirement: The output cap is idempotent and tests can drive it directly

Cutting a file to its limit SHALL keep the limit minus the marker's length of tail, SHALL leave alone a file that already
begins with the marker and is within the limit, and the loop that runs it SHALL signal after each pass, so a test calls
the cut or waits on the signal and never polls the file.

#### Scenario: A file already cut

- **GIVEN** a file that begins with the marker and is within the limit
- **WHEN** the cut runs again
- **THEN** the file is not rewritten

#### Scenario: A writer holding the file

- **GIVEN** a writer with the file open that opened it with a plain redirect
- **WHEN** the cut runs between its writes
- **THEN** the marker and the tail are kept, and the next cut removes the hole its next write leaves

### Requirement: A hung test fails within a time limit

Every test SHALL run under a time limit that fails it, from a thread, when exceeded; a test of the tier-2 marker runs under a longer limit of its own (see `tier2-tests-have-their-own-time-limit`).

#### Scenario: A test that hangs

- **WHEN** a test does not return within the limit
- **THEN** it fails with the limit named and the run continues

### Requirement: A command that does not finish fails with where it was waiting

Every command unit-test runs SHALL have a limit on the time it may take, configurable, SHALL be asked to abort when it passes the
limit so its runtime can dump the stacks of its threads, SHALL be ended after a short grace, and SHALL fail unit-test with a message
that names the command and the time and carries the end of its output, dump included.

#### Scenario: Tests pass and the process does not exit

- **GIVEN** a test run in which every test passes and a thread keeps the process alive
- **WHEN** the limit passes
- **THEN** the command is aborted, unit-test fails naming the command and the time, and the output shows the waiting threads

#### Scenario: A command that finishes in time

- **WHEN** a command finishes within its limit
- **THEN** it is not signalled and its result is judged as before

#### Scenario: A process that ignores the abort

- **GIVEN** a process that does not end when asked to abort
- **WHEN** the grace has passed
- **THEN** it is ended and unit-test still fails with the message

### Requirement: Tests do not use bare timing hazards

The tests SHALL NOT use a bare sleep, a thread that nothing joins or signals, or a fixed port, except in the shared
helpers and in files on an allowlist that records existing uses. The allowlist SHALL NOT grow, and a file SHALL leave it
when its uses are gone.

#### Scenario: A new sleep

- **WHEN** a test file not on the allowlist uses a bare sleep
- **THEN** the guard test fails naming the file and the line

#### Scenario: A file leaves the allowlist

- **GIVEN** a file on the allowlist whose uses have been removed
- **WHEN** the guard runs
- **THEN** it fails until the file is removed from the allowlist

### Requirement: Tests a unit adds or changes are checked for flakiness

After unit-test passes, the tests a unit added or changed SHALL be run again several times under the same parallel load,
and any failure SHALL fail unit-test with the output.

#### Scenario: A new test that fails one run in five

- **GIVEN** a test added by the unit that fails under load in one of its repeated runs
- **WHEN** the repeat check runs
- **THEN** unit-test fails with that run's output

#### Scenario: Only the unit's tests

- **WHEN** the repeat check runs
- **THEN** it runs the tests the unit added or changed and no others

### Requirement: Agents are told what makes a test deterministic

The prompt for writing tests and the reviewer's checklist for tests SHALL tell the agent not to wait on the clock, to
inject the clock or sleep or wait on an event, not to start a thread that nothing joins or signals, to bind a free port,
not to share a temporary path between tests, not to assert a state that a background actor repairs later, and that code
that runs on a timer or thread exposes a step that tests call directly. A change that introduces such a use SHALL be a
required finding.

#### Scenario: A sleep in a new test

- **GIVEN** a diff whose new test waits with a sleep
- **WHEN** the reviewer reviews it
- **THEN** the finding is required and its consequence is that the test passes alone and fails under load
