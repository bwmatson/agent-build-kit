## ADDED Requirements

### Requirement: A test is marked serial only for a stated reason

A test marked as needing exclusivity SHALL carry a one-line reason beside the marker that names what it
cannot share with another test. The whole-suite command SHALL run a serial pass only while at least one
test carries the marker, and SHALL NOT describe the marker as unused when it is used or used when it is not.

#### Scenario: A marker with a reason

- **GIVEN** a module marked serial
- **WHEN** its source is read
- **THEN** a line beside the marker says what it cannot share

#### Scenario: No marked test

- **GIVEN** no test carries the marker
- **WHEN** the whole-suite command is run
- **THEN** it runs no serial pass and every test runs in the parallel pass

### Requirement: No two test modules share a session identifier

A test that starts a process or names a session SHALL use an identifier made for that test, not a
constant defined in a module, so no two tests running at once in any worker name the same one. A guard
test SHALL fail when two test or test support files define the same constant session identifier.

#### Scenario: Two tests in different workers

- **GIVEN** two chat tests that each start a process carrying a session identifier
- **WHEN** they run at the same time
- **THEN** each finds only its own process

#### Scenario: A repeated constant

- **GIVEN** two files that define the same constant session identifier
- **WHEN** the guard test runs
- **THEN** it fails naming the identifier and both files

### Requirement: A lookup of who holds a session can be pointed at another process table

The lookup of which processes hold a session SHALL accept the location of the process table to read, with
the machine's own as the default, so a test can answer it from a table it built. The destructive steps
SHALL still refuse any table but the machine's own.

#### Scenario: A private table

- **GIVEN** a process table built in a temporary directory with one entry carrying a session identifier
- **WHEN** the lookup is given that location
- **THEN** it returns that entry and reads nothing from the machine's table

#### Scenario: The default

- **GIVEN** no location
- **WHEN** the lookup runs
- **THEN** it reads the machine's own table, as before
