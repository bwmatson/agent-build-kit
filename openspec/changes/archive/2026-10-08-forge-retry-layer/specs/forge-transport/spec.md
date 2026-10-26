## MODIFIED Requirements

### Requirement: Calls to a code host go through one transport with timeouts and bounded retry

The framework SHALL reach a code host over HTTP through one transport that applies a
timeout to every call and raises typed errors, and SHALL decide what to repeat in exactly one
layer above both forges: a transient failure of a read or an idempotent write, and a rate limit,
SHALL be retried a bounded number of times with backoff and a total deadline, honouring the host's
retry hint. A create SHALL NOT be repeated unless a read declared for it shows it did not land.
A permanent failure SHALL NOT be retried.

#### Scenario: A transient server error

- **GIVEN** a host that answers 503 once and then succeeds
- **WHEN** a read is made
- **THEN** it succeeds after a retry

#### Scenario: A host that stays down

- **WHEN** every attempt fails
- **THEN** the call fails after the bound with a typed error, not a hang

#### Scenario: A write that creates something

- **GIVEN** a timed-out request to create a comment
- **WHEN** the call fails
- **THEN** it is not repeated unless a read shows the comment did not land

## ADDED Requirements

### Requirement: Every forge operation declares how it may be repeated

Each operation of the forge protocol SHALL declare one kind: read, idempotent write, create or
advisory. A create SHALL also name the read that shows whether it landed. The retry layer SHALL
apply the rule for the kind, for every host, and a protocol method with no declaration SHALL fail
a test.

#### Scenario: A status post is repeated

- **GIVEN** a commit status post that answers 503 once
- **WHEN** it is made
- **THEN** it is repeated and succeeds

#### Scenario: A create that landed

- **GIVEN** a pull request create that times out after the host created the pull request
- **WHEN** the layer retries
- **THEN** it finds the pull request with the declared read and returns it without creating again

#### Scenario: A client error

- **WHEN** a call is answered 404 or 401
- **THEN** it is not retried

#### Scenario: An advisory call that cannot complete

- **WHEN** a label add fails after every attempt
- **THEN** the failure is logged and counted and the caller continues

### Requirement: An exhausted call raises one typed error

When every attempt of a call has failed transiently, the retry layer SHALL raise an error naming
the operation, the cause and the attempts, distinguishable from a call the host refused.

#### Scenario: The host is unavailable

- **WHEN** every attempt of a read fails with a server error
- **THEN** the error says the host is unavailable for that operation

### Requirement: Retries are visible

Each retry SHALL be logged with its operation, attempt and cause, and counted by operation and
outcome.

#### Scenario: A retried call

- **WHEN** a call is retried
- **THEN** a log line and a counter increment record it
