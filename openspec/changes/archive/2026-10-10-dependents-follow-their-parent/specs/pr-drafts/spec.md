## ADDED Requirements

### Requirement: A pull request is a draft whenever the pipeline is not waiting for a reviewer

A unit's open pull request SHALL be a draft while the unit is running or planned and ready for review
while it is in review. A host without drafts, a closed pull request or a failed call SHALL be skipped
and logged, and SHALL NOT change the unit.

#### Scenario: A unit goes back to planned

- **GIVEN** a unit in review with a ready pull request
- **WHEN** the unit is set back to planned
- **THEN** its pull request is made a draft

#### Scenario: The unit returns to review

- **GIVEN** a unit that is planned with a draft pull request
- **WHEN** the unit is in review again
- **THEN** the pull request is published for review

#### Scenario: A host without drafts

- **WHEN** a unit leaves review on a host that has no drafts
- **THEN** the unit changes state and the missing draft is logged
