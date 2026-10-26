## ADDED Requirements

### Requirement: The poller records every check's status

The poller SHALL record each check's name and status in a pull request's snapshot, SHALL treat a
change from pending to failed as newly failing, and SHALL record a snapshot written before this change
afresh without sending the unit back.

#### Scenario: A check finishes failing

- **GIVEN** a snapshot with a pending check
- **WHEN** the check fails
- **THEN** the unit is sent back for rework naming the check

#### Scenario: An older snapshot

- **GIVEN** a snapshot that holds failing and cancelled names only
- **WHEN** the pull request is polled
- **THEN** the snapshot is recorded afresh and nothing is sent back

### Requirement: A change in a pull request's checks refreshes its label

When the poller records checks that change the status a unit in review reads, it SHALL bring the pull request's state label in
line with it, without waiting for the unit's stored state to change.

#### Scenario: Checks begin

- **GIVEN** a unit in review whose pull request carries the `in_review` label
- **WHEN** the poll records a pending check
- **THEN** the label becomes `checking`

#### Scenario: Checks pass

- **GIVEN** a pull request labelled `checking`
- **WHEN** the poll records every check as passed
- **THEN** the label becomes `in_review`
