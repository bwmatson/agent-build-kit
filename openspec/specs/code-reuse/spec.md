# code-reuse Specification

## Purpose
TBD - created by archiving change dry-cleanup. Update Purpose after archive.

## Requirements

### Requirement: A metric with a local record is emitted through one function

A metric that is also recorded locally SHALL be emitted through one function that does both, no code SHALL make the
two calls separately, and the metrics page SHALL still list the instrument. Metrics with no local record are
unaffected.

#### Scenario: A metric emit site

- **WHEN** the pipeline emits a metric that has a local record
- **THEN** it calls the one function, and a test fails if any function other than the helper calls the local
  record

#### Scenario: Telemetry off

- **WHEN** telemetry is off and such a metric is emitted
- **THEN** the local record is still written with the same name, value and attributes

#### Scenario: The metrics page

- **WHEN** the metrics page lists the instruments the code emits
- **THEN** the instruments emitted through the helper are listed with the type and attributes they had before

### Requirement: A failure is classified once

The kind of a unit-test failure SHALL be worked out once at each failure site and used for every purpose at that site.

#### Scenario: One failure, one classification

- **WHEN** unit-test fails
- **THEN** the classification is computed once and the telemetry and the stored feedback use the same result

#### Scenario: Open entries derived once

- **WHEN** the stack runner lists the unresolved entries and renders them
- **THEN** both come from one computation of the open entries

### Requirement: State files are written by one function

A state file SHALL be written by one atomic write, and a module that adds a state file SHALL use it.

#### Scenario: A state file is written

- **WHEN** any module writes a state file
- **THEN** it uses the shared atomic write, and the file is never seen half-written

#### Scenario: An interrupted write

- **WHEN** a write is interrupted
- **THEN** the previous content stays and no temporary file is left

#### Scenario: Writers at once

- **WHEN** two processes write one file at once
- **THEN** they do not share a temporary name

#### Scenario: A new write of its own

- **WHEN** a module replaces a file from a temporary one without the shared function
- **THEN** the test that guards this fails

### Requirement: Common helpers are defined once

The pipeline SHALL run the version-control command through one runner, take where a change's files live from one
function, and define the pattern that recognises a code host's remote address and the diff-hunk pattern once each,
and no two modules under `src/` SHALL define the same module-level compiled pattern.

#### Scenario: A plain git call

- **WHEN** the init command, the commit gate or the scaffold runs the version-control command
- **THEN** it does so through the shared runner and gets the results it did before

#### Scenario: A change's directory

- **WHEN** a step needs the directory of a change
- **THEN** it takes it from the one layout function, whatever the specs directory is called

#### Scenario: Two modules define one pattern

- **WHEN** a module under `src/` defines a compiled pattern equal to one defined in another module
- **THEN** the test that guards this fails

### Requirement: The code hosts share what they have in common

GitHub's listing of a pull request's file paths SHALL be derived from its fuller listing, and the hosts' helpers that
parse an answer SHALL share the step that validates the body and names the endpoint when it is not the document
expected.

#### Scenario: Listing files

- **WHEN** the paths of a pull request's files are asked for on GitHub
- **THEN** they come from the same paged call as the full listing, which is made once

#### Scenario: The other hosts' listings

- **WHEN** the paths or changes of a pull request are asked for on Azure DevOps or the local forge
- **THEN** they answer as before

#### Scenario: A body that is not the document expected

- **WHEN** either host's parsing helper is given a body that does not validate
- **THEN** both raise the same transport error naming the endpoint

### Requirement: Test helpers are defined once

The helpers that make a commit, write a change, build an installation and fake the change tooling SHALL be defined
once in the shared test modules where they were copied identically, and no test file SHALL define its own copy.

#### Scenario: A test needs a commit

- **WHEN** a test file needs to commit a file
- **THEN** it imports the shared helper

#### Scenario: A helper defined twice

- **WHEN** two test files define a helper of the same name and the same body, or a merged helper is defined again
- **THEN** the guard test fails, and a same-named helper with a different body does not
