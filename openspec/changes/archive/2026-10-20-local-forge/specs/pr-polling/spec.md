## ADDED Requirements

### Requirement: A local pull request is polled as any other

The poller SHALL treat a local forge's pull requests as it treats a host's: new comments and a
changes-requested decision send the unit back, and a merge reported by git moves it on.

#### Scenario: Request changes on a local pull request

- **WHEN** a reviewer requests changes in the UI on a local pull request
- **THEN** the unit is sent back for rework

#### Scenario: The merge

- **WHEN** git shows the branch merged
- **THEN** the unit is recorded merged and its dependents are released
