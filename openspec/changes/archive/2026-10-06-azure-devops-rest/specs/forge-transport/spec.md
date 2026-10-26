## ADDED Requirements

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
