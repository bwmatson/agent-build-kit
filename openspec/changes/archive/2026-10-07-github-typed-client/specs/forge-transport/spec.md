## ADDED Requirements

### Requirement: GitHub is reached through a typed client without the host CLI

The GitHub forge SHALL perform every operation it performs today through a typed client
over authenticated HTTP, with a client per owner, explicit timeouts and bounded retry,
and SHALL NOT start the host CLI to make a call. The CLI MAY remain a source of
credentials. The forge SHALL return the same pull-request records it returns today for
the same host state.

#### Scenario: Listing pull requests

- **GIVEN** a repository with pull requests that have comments, reviews and checks
- **WHEN** the pipeline lists them
- **THEN** it returns the same fields as before from one query per page, with no
  subprocess started

#### Scenario: A check cancelled by the host

- **WHEN** a check's conclusion is cancelled
- **THEN** it is reported as cancelled and not as failing

#### Scenario: Two owners at once

- **WHEN** units for two owners call GitHub concurrently
- **THEN** each call is made with its own owner's credential

### Requirement: Stacked pull requests keep working

The forge SHALL create, read and extend stacks through the host's stack endpoints and
SHALL report a concurrent-modification conflict as it does today.

#### Scenario: A concurrent stack change

- **GIVEN** a host that answers a stack call with a conflict
- **WHEN** the pipeline adds a pull request to the stack
- **THEN** the refusal is reported as concurrent
