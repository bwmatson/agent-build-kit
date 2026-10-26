## ADDED Requirements

### Requirement: A unit in review reads checking while its checks run

A unit in review SHALL be shown as `checking` while any of its pull request's checks is pending, or
while it has none within `limits.checks_register_seconds` of its last push, and as `in_review` once its
checks have passed or that window has ended with none. The status SHALL be derived, SHALL count as in
review for scheduling, and SHALL be what the status command, the graph and the state label show. The
status command SHALL list a checking unit with its pull request link as it lists one awaiting review.

#### Scenario: Checks are running

- **GIVEN** a unit in review with a pending check
- **WHEN** its status is read
- **THEN** it is `checking` and the status command lists it with its pull request link

#### Scenario: Checks passed

- **WHEN** every check has passed
- **THEN** the unit reads `in_review` and is listed as awaiting review

#### Scenario: Just pushed, no checks yet

- **GIVEN** a unit pushed seconds ago whose pull request has no checks
- **WHEN** its status is read
- **THEN** it is `checking`

#### Scenario: A repo with no checks

- **GIVEN** a pull request with no checks, pushed longer ago than the window
- **WHEN** its status is read
- **THEN** it reads `in_review`

#### Scenario: Scheduling is unchanged

- **WHEN** a unit is checking
- **THEN** it holds a queue place and releases its dependents exactly as one in review does
