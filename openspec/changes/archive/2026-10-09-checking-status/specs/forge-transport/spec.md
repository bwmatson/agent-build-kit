## ADDED Requirements

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
