# forge-transport Specification

## Purpose
TBD - created by archiving change forge-http-transport. Update Purpose after archive.

## Requirements

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

### Requirement: Azure DevOps is reached over typed REST without the host CLI

The Azure DevOps forge SHALL perform every operation it performs today through
authenticated REST calls made by the framework's transport, SHALL parse responses into
typed models, and SHALL NOT start the host CLI to make a call. The CLI MAY remain a
source of credentials. The forge SHALL return the same pull-request records it returns
today for the same host state.

#### Scenario: Listing pull requests

- **GIVEN** a project with open pull requests that have threads, policy evaluations and
  statuses
- **WHEN** the pipeline lists them
- **THEN** it returns the same fields as before, with no subprocess started

#### Scenario: A failing check that was cancelled

- **GIVEN** a policy evaluation that failed because its build was cancelled
- **WHEN** the pull requests are listed
- **THEN** the check is reported as cancelled, not failing

#### Scenario: Retargeting a pull request's base

- **WHEN** a base already equal to the target is requested
- **THEN** no write is made

### Requirement: Reads for many pull requests are bounded and paged

Listing SHALL read each open pull request's threads, policy evaluations and statuses
with bounded concurrency in one process, SHALL follow continuation tokens and paging
parameters to the end, and SHALL read nothing more for a closed or merged pull request
than the list call returns.

#### Scenario: More results than a page

- **WHEN** a list is paged by continuation token
- **THEN** every page is read

#### Scenario: Many open pull requests

- **WHEN** twenty pull requests are open
- **THEN** reads never exceed the concurrency bound

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

### Requirement: A lookup distinguishes none from unknown

A forge's pull request lookup SHALL return nothing only when the host answered that there is no
pull request, and SHALL raise when it could not tell. A create refused because the pull request
already exists SHALL return that pull request.

#### Scenario: The host is down during a lookup

- **GIVEN** a host that cannot be reached
- **WHEN** the pipeline looks for a pull request by its head
- **THEN** the lookup raises and does not report that none exists

#### Scenario: A duplicate create

- **GIVEN** a pull request that already exists for a head and base
- **WHEN** a create is refused as a duplicate
- **THEN** the existing pull request is returned

### Requirement: A forge can say whether a comment already exists

Each forge SHALL answer whether a comment carrying the pipeline's marker and a given body exists
on a pull request, or as a reply to a given comment, and return its identifier when it does.

#### Scenario: A comment that landed

- **GIVEN** a reply the host stored although its answer was lost
- **WHEN** the existence of that reply is asked
- **THEN** its identifier is returned

#### Scenario: No such comment

- **WHEN** no comment matches
- **THEN** nothing is returned

### Requirement: A failed follow-up to a create does not fail the unit

After a pull request exists, a failure to update its body or to post its status SHALL be logged and
counted and SHALL NOT fail the unit, on every host.

#### Scenario: A status post fails after the create

- **GIVEN** a pull request just created
- **WHEN** posting its status fails
- **THEN** the unit continues to review

### Requirement: An owed reply is kept until it is posted

A reply or comment the pipeline owes a pull request SHALL stay pending until it has been posted or
found already posted, and SHALL be attempted again on a later pass when it could not be posted. A
reply SHALL NOT be posted twice.

#### Scenario: A reply fails once

- **GIVEN** a reply that the host refuses on every attempt of one pass
- **WHEN** the next pass runs and the host answers
- **THEN** the reply is posted once and removed from the pending list

#### Scenario: A reply that landed

- **GIVEN** a reply the host stored although its answer was lost
- **WHEN** the pass attempts it again
- **THEN** it is recognised as posted and not posted again

### Requirement: A satisfied unit's pull request is closed

A satisfied unit's pull request SHALL be closed by posting the reason and closing it, repeated on
later passes until both are done, without posting the reason twice.

#### Scenario: The host fails after the reason is posted

- **GIVEN** a reason posted and a close that failed
- **WHEN** the next pass runs
- **THEN** the pull request is closed and the reason is not posted again

### Requirement: A pull request's checks are one list with a status each

A pull request SHALL carry a list of checks, each with a name, one of the statuses `passed`, `failed`,
`cancelled` or `pending`, and an optional link. Each forge SHALL map its host's words into these
statuses, an unknown host value SHALL map to `pending`, and the failing and cancelled names SHALL be
read from the list rather than kept separately. The overall result SHALL be derived: failed when any
check failed, otherwise pending when any is pending, otherwise passed, and none when the list is empty.

#### Scenario: GitHub check runs

- **GIVEN** a commit with a passing, a failing, a cancelled and an in-progress check run
- **WHEN** the pull request is read
- **THEN** the list has one check of each status, and the overall result is failed

#### Scenario: Azure DevOps statuses

- **GIVEN** a pull request with several postings for one status context, the latest pending
- **WHEN** it is read
- **THEN** the context is one pending check

#### Scenario: An Azure DevOps build policy

- **GIVEN** a rejected build evaluation whose build was cancelled, and a running one
- **WHEN** the pull request is read
- **THEN** the first is a cancelled check and the second a pending one

#### Scenario: An unknown host value

- **WHEN** a host reports a check state the forge does not know
- **THEN** it is a pending check and the unit is not sent back

#### Scenario: Every reader uses the list

- **WHEN** the poller finds a failing check
- **THEN** the unit is sent back as before, naming the failing checks from the list
