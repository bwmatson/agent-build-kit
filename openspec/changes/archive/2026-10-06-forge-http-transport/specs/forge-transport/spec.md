## ADDED Requirements

### Requirement: Calls to a code host go through one transport with timeouts and bounded retry

The framework SHALL reach a code host over HTTP through one transport that applies a
timeout to every call and retries network errors, timeouts, rate limits and server
errors a bounded number of times with backoff, honouring the host's retry hint. A write
that is not idempotent SHALL NOT be retried unless the caller says it is safe.

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
- **THEN** it is not repeated

### Requirement: Credentials are chosen per owner and never put in an argument list

The transport SHALL resolve a credential for each owner or organisation from the
repository's setting, else from the logged-in host CLI as a source only, SHALL cache it
for the process, and SHALL NOT place a token in an argument list or change any global
state to select it, so units for different owners can run concurrently.

#### Scenario: Two owners at once

- **WHEN** units for two owners call their hosts concurrently
- **THEN** each call carries its own owner's credential

#### Scenario: No credential

- **WHEN** no source yields a credential for an owner
- **THEN** the call fails with an error naming the owner and the sources tried

### Requirement: An answer that is not the expected one is an error

The transport SHALL treat a response that is not the expected media type, such as a
sign-in page returned with a success status, as an authentication error, and SHALL name
the account used when a repository is reported as not found.

#### Scenario: A sign-in page

- **GIVEN** a host that answers 200 with an HTML sign-in page
- **WHEN** a JSON endpoint is called
- **THEN** an authentication error is raised, not an empty result

#### Scenario: A private repository on the wrong account

- **WHEN** a repository is not found
- **THEN** the error names the account the call was made as

### Requirement: Doctor checks credentials, not binaries

`abk doctor` SHALL, for each repository, resolve its credential and call the host's
cheapest authenticated endpoint, reporting the account or the failing source.

#### Scenario: A logged-out machine

- **WHEN** no credential resolves for a repository
- **THEN** doctor fails that repository naming the sources it tried
