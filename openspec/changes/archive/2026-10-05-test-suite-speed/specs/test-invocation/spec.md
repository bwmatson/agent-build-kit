## ADDED Requirements

### Requirement: The whole-suite command uses the machine's cores

A repo's documented whole-suite command SHALL distribute its tests across
worker processes, so that the suite's duration falls with the cores available
instead of staying that of one process. Running a single test file SHALL NOT
require, or be slowed by, the workers. Distribution SHALL NOT change which tests
run or whether they pass: a test that cannot share a process with others SHALL
be marked and run in a serial pass of the same command.

#### Scenario: The whole suite on a many-core host

- **WHEN** the whole-suite command is run on a host with many cores
- **THEN** every test it ran serially is run
- **AND** the run finishes in a fraction of the serial time

#### Scenario: A single test file

- **WHEN** `pytest` is given one test file
- **THEN** it runs in one process without starting workers

#### Scenario: A test that cannot run beside others

- **GIVEN** a test marked as needing exclusivity
- **WHEN** the whole-suite command is run
- **THEN** it runs alone, in a serial pass, and passes
